'use client';
import { useEffect, useRef, useState } from 'react';

const LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
const PK_CENTER   = [30.3753, 69.3451];
// OpenStreetMap's own tiles (no key). The dark theme darkens them with a CSS
// filter on the tile layer only (`.lm-wrap .leaflet-tile-pane`), so pins and
// controls keep their colours. (CARTO's dark basemap was tried: it now needs
// an API key.) OSM's licence asks for the credit, so attribution stays on.
const TILES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const CREDIT = '&copy; OpenStreetMap contributors';

/* The pins (2026-10-10): a pill with the consultation fee ("Rs 3k"), or the
 * lawyer's initials when no fee is set. Pure CSS, no image requests. The text
 * is built only from numbers and letters and is escaped all the same: a
 * lawyer's name is theirs to write. An approximate pin (a province centre,
 * not an office) has a dashed edge. */
const PIN_CSS = `.lm-pin{display:inline-flex;align-items:center;justify-content:center;height:30px;padding:0 11px;border-radius:999px;white-space:nowrap;font:700 12.5px "Hanken Grotesk",system-ui,sans-serif;color:#F1F5F6;background:#183840;border:1.5px solid rgba(150,215,220,.35);box-shadow:0 6px 16px -6px rgba(0,0,0,.6);cursor:pointer;transform:translate(-50%,-50%);transition:transform .15s ease,background .15s,border-color .15s}
.lm-pin.approx{border-style:dashed}
.lm-pin.off{color:#93A4A8}
.lm-pin:hover,.lm-pin.hot{transform:translate(-50%,-50%) scale(1.08);border-color:#5EE6B0}
.lm-pin.on{background:linear-gradient(135deg,#3EE0A1,#2EC4D6);color:#04212A;border-color:transparent;transform:translate(-50%,-50%) scale(1.12);box-shadow:0 0 0 4px rgba(62,224,161,.25),0 10px 22px -8px rgba(46,196,214,.8)}
.lm-wrap .leaflet-tile-pane{filter:invert(1) hue-rotate(180deg) brightness(.82) contrast(.92) saturate(.55)}
.lm-wrap.light .leaflet-tile-pane{filter:saturate(.6) brightness(1.02)}
.lm-wrap .leaflet-control-zoom{border:0!important;box-shadow:none!important;display:flex;flex-direction:column;gap:6px;margin:14px 14px 0 0!important}
.lm-wrap .leaflet-control-zoom a{width:36px!important;height:36px!important;line-height:34px!important;border-radius:11px!important;border:1px solid rgba(150,215,220,.22)!important;background:#183840!important;color:#F1F5F6!important;font-size:18px!important}
.lm-wrap .leaflet-control-zoom a:hover{background:#1E4550!important;color:#6FEBBB!important}
.lm-wrap.light .leaflet-control-zoom a{background:#fff!important;color:#1E1C21!important;border-color:#DFDCE3!important}
.lm-ctrls{position:absolute;top:14px;right:14px;z-index:650;display:flex;flex-direction:column;gap:10px}
.lm-ctrls .grp{display:flex;flex-direction:column;padding:4px;gap:2px;border-radius:14px;background:rgba(24,56,64,.94);border:1px solid rgba(150,215,220,.22);box-shadow:0 12px 24px -14px rgba(0,0,0,.7);backdrop-filter:blur(8px)}
.lm-ctrls button{width:36px;height:36px;border:0;border-radius:10px;background:transparent;color:#F1F5F6;display:grid;place-items:center;cursor:pointer;transition:background .15s,color .15s}
.lm-ctrls button:hover:not(:disabled){background:rgba(62,224,161,.12);color:#6FEBBB}
.lm-ctrls button[aria-pressed="true"]{color:#5EE6B0}
.lm-ctrls button:disabled{opacity:.45;cursor:wait}
.lm-wrap.light .lm-ctrls .grp{background:rgba(255,255,255,.95);border-color:#DFDCE3}
.lm-wrap.light .lm-ctrls button{color:#1E1C21}
.lm-wrap.light .lm-ctrls button:hover:not(:disabled){background:rgba(14,138,95,.08);color:#0E7A55}
.lm-me{position:relative;width:16px;height:16px;transform:translate(-50%,-50%)}
.lm-me i{position:absolute;inset:0;border-radius:50%;background:#3CCFE0;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.5)}
.lm-me b{position:absolute;inset:-10px;border-radius:50%;background:rgba(60,207,224,.35);animation:lmPulse 1.8s ease-out infinite}
@keyframes lmPulse{from{transform:scale(.4);opacity:1}to{transform:scale(1.6);opacity:0}}
@media (prefers-reduced-motion:reduce){.lm-me b{animation:none}}
.lm-wrap .leaflet-control-attribution{background:rgba(15,36,41,.7)!important;color:#93A4A8!important;font-size:10px!important}
.lm-wrap .leaflet-control-attribution a{color:#BFCACC!important}
.lm-wrap.light .leaflet-control-attribution{background:rgba(255,255,255,.75)!important;color:#5A5660!important}`;

const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pinText = l => {
    if (l.fee) return l.fee >= 1000 ? `Rs ${Math.round(l.fee / 100) / 10}k` : `Rs ${l.fee}`;
    return String(l.name || '?').split(/\s+/).map(w => w[0] || '').join('').slice(0, 2).toUpperCase();
};

function makeIcon(L, l, state) {
    const cls = ['lm-pin', l.precision === 'approximate' ? 'approx' : '', l.avail ? '' : 'off', state].filter(Boolean).join(' ');
    return L.divIcon({ className: '', html: `<div class="${cls}">${esc(pinText(l))}</div>`, iconSize: [0, 0] });
}

/* `onSelect(lawyer)`: a pin was chosen. `selectedId` / `hoveredId` mark one pin
 * (the map flies to the selected one). `height` is px or any CSS length.
 * `dark`: the basemap and controls for the dark theme. `leftInset`: px of the
 * map covered by a panel on its left; fitting the pins keeps clear of it.
 * `controls`: the map's own control column (zoom, "my location", map style,
 * show all) in place of Leaflet's zoom box. "My location" asks the browser
 * once, on the click; the position goes to `onLocate({lat,lng})` (or
 * `onLocate(null, message)`) and nowhere else -- never to the server. */
export default function LeafletMap({ lawyers = [], onSelect, height = 340, selectedId = null, hoveredId = null, dark = true, leftInset = 0, controls = false, onLocate }) {
    const containerRef = useRef(null);
    const stateRef     = useRef(null); // { L, map, tiles }
    const markersRef   = useRef(new Map()); // id -> { marker, lawyer }
    const selectRef    = useRef(onSelect);
    selectRef.current  = onSelect;
    const insetRef     = useRef(leftInset);
    insetRef.current   = leftInset;
    const meRef        = useRef(null);        // the "you are here" marker
    const [mapDark, setMapDark] = useState(dark);
    const [locating, setLocating] = useState(false);
    const [me, setMe] = useState(null);
    useEffect(() => { setMapDark(dark); }, [dark]);

    const idOf = l => String(l._id || l.bar || l.name);

    // ── bootstrap the map once ─────────────────────────────────────
    useEffect(() => {
        let alive = true;
        (async () => {
            try {
                const { default: L } = await import('leaflet');
                if (!alive || !containerRef.current) return;
                if (!document.getElementById('leaflet-css')) {
                    document.head.appendChild(Object.assign(document.createElement('link'), { id: 'leaflet-css', rel: 'stylesheet', href: LEAFLET_CSS }));
                }
                const map = L.map(containerRef.current, { scrollWheelZoom: true, attributionControl: true, zoomControl: false }).setView(PK_CENTER, 5);
                if (!controls) L.control.zoom({ position: 'topright' }).addTo(map);
                map.attributionControl.setPrefix(false);
                const tiles = L.tileLayer(TILES, { maxZoom: 18, attribution: CREDIT }).addTo(map);
                stateRef.current = { L, map, tiles };
                placeMarkers(true);
            } catch {
                // The map is optional: without Leaflet the list still works.
            }
        })();
        return () => {
            alive = false;
            if (stateRef.current) { stateRef.current.map.remove(); stateRef.current = null; }
            markersRef.current = new Map();
            meRef.current = null;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // ── the pins, when the list changes ────────────────────────────
    useEffect(() => { placeMarkers(true); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [lawyers]);

    // ── the chosen / hovered pin ───────────────────────────────────
    useEffect(() => {
        const s = stateRef.current;
        if (!s) return;
        for (const [id, { marker, lawyer }] of markersRef.current) {
            const state = id === String(selectedId) ? 'on' : id === String(hoveredId) ? 'hot' : '';
            marker.setIcon(makeIcon(s.L, lawyer, state));
            marker.setZIndexOffset(state === 'on' ? 1000 : state === 'hot' ? 500 : 0);
        }
        const chosen = selectedId != null && markersRef.current.get(String(selectedId));
        if (chosen) s.map.flyTo(chosen.marker.getLatLng(), Math.max(s.map.getZoom(), 7), { duration: 0.6 });
    }, [selectedId, hoveredId]);

    function placeMarkers(fit) {
        const s = stateRef.current;
        if (!s) return;
        markersRef.current.forEach(({ marker }) => marker.remove());
        markersRef.current = new Map();
        const pins = lawyers.filter(l => l.lat != null && l.lng != null);
        pins.forEach(l => {
            const id = idOf(l);
            const state = id === String(selectedId) ? 'on' : '';
            const marker = s.L.marker([l.lat, l.lng], { icon: makeIcon(s.L, l, state), keyboard: true, title: l.name })
                .addTo(s.map)
                .on('click', () => selectRef.current?.(l));
            markersRef.current.set(id, { marker, lawyer: l });
        });
        if (!fit) return;
        const pad = { paddingTopLeft: [60 + insetRef.current, 60], paddingBottomRight: [60, 60], maxZoom: 9 };
        if (pins.length > 1) s.map.fitBounds(s.L.latLngBounds(pins.map(l => [l.lat, l.lng])), pad);
        else if (pins.length === 1) s.map.fitBounds(s.L.latLngBounds([[pins[0].lat, pins[0].lng]]), { ...pad, maxZoom: 7 });
    }

    // Every pin (and you, once located) in view, clear of the left panel.
    function fitAll() {
        const s = stateRef.current;
        if (!s) return;
        const pts = lawyers.filter(l => l.lat != null && l.lng != null).map(l => [l.lat, l.lng]);
        if (me) pts.push([me.lat, me.lng]);
        if (!pts.length) { s.map.setView(PK_CENTER, 5); return; }
        s.map.fitBounds(s.L.latLngBounds(pts), { paddingTopLeft: [60 + insetRef.current, 60], paddingBottomRight: [60, 60], maxZoom: pts.length > 1 ? 11 : 9 });
    }
    function locate() {
        const s = stateRef.current;
        if (!s || locating) return;
        if (!navigator.geolocation) { onLocate?.(null, 'Your browser cannot share its location.'); return; }
        setLocating(true);
        navigator.geolocation.getCurrentPosition(pos => {
            setLocating(false);
            const here = { lat: pos.coords.latitude, lng: pos.coords.longitude };
            setMe(here);
            if (meRef.current) meRef.current.remove();
            meRef.current = s.L.marker([here.lat, here.lng], {
                icon: s.L.divIcon({ className: '', html: '<div class="lm-me"><b></b><i></i></div>', iconSize: [0, 0] }),
                title: 'You are here', zIndexOffset: 2000, keyboard: false,
            }).addTo(s.map);
            s.map.flyTo([here.lat, here.lng], Math.max(s.map.getZoom(), 10), { duration: 0.8 });
            onLocate?.(here);
        }, err => {
            setLocating(false);
            onLocate?.(null, err && err.code === 1 ? 'Location permission was not given.' : 'Your location could not be found.');
        }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
    }
    const icon = d => <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>;

    return (
        <div className={`lm-wrap${mapDark ? '' : ' light'}`} style={{ height, width: '100%', position: 'relative' }}>
            <style>{PIN_CSS}</style>
            <div ref={containerRef} style={{ height: '100%', width: '100%', background: mapDark ? '#0F2429' : '#EBE9EE' }} />
            {controls && (
                <div className="lm-ctrls">
                    <div className="grp" role="group" aria-label="Map">
                        <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => stateRef.current?.map.zoomIn()}>{icon(<><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5M11 8v6M8 11h6" /></>)}</button>
                        <button type="button" aria-label="Zoom out" title="Zoom out" onClick={() => stateRef.current?.map.zoomOut()}>{icon(<><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5M8 11h6" /></>)}</button>
                        <button type="button" aria-label="My location" title="Show my location" aria-pressed={Boolean(me)} disabled={locating} onClick={locate}>{icon(<path d="M3 11l18-8-8 18-2-8z" />)}</button>
                    </div>
                    <div className="grp" role="group" aria-label="View">
                        <button type="button" aria-label={mapDark ? 'Light map' : 'Dark map'} title={mapDark ? 'Light map' : 'Dark map'} onClick={() => setMapDark(d => !d)}>
                            {mapDark ? icon(<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />) : icon(<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>)}
                        </button>
                        <button type="button" aria-label="Show every lawyer" title="Show every lawyer" onClick={fitAll}>{icon(<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />)}</button>
                    </div>
                </div>
            )}
        </div>
    );
}
