'use client';
import { useEffect, useRef } from 'react';

const LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
const PK_CENTER   = [30.3753, 69.3451];

// Pure-CSS pin — no external image requests, no CDN dependency
function makeIcon(L, available) {
    const color = available ? '#3b82f6' : '#6b7280';
    return L.divIcon({
        className: '',
        html: `<div style="
            width:14px;height:14px;
            background:${color};
            border:2.5px solid #fff;
            border-radius:50%;
            box-shadow:0 2px 6px rgba(0,0,0,0.45);
        "></div>`,
        iconSize:    [14, 14],
        iconAnchor:  [7,  7],
        popupAnchor: [0, -10],
    });
}

export default function LeafletMap({ lawyers = [], onSelect, height = 340 }) {
    const containerRef = useRef(null);
    const stateRef     = useRef(null); // { L, map }
    const markersRef   = useRef([]);

    // ── bootstrap map once on mount ───────────────────────────────
    useEffect(() => {
        let alive = true;

        const bootstrap = async () => {
            try {
                const { default: L } = await import('leaflet');
                if (!alive || !containerRef.current) return;

                if (!document.getElementById('leaflet-css')) {
                    const link = Object.assign(document.createElement('link'), {
                        id: 'leaflet-css', rel: 'stylesheet', href: LEAFLET_CSS,
                    });
                    document.head.appendChild(link);
                }

                const map = L.map(containerRef.current, {
                    scrollWheelZoom: false,
                    attributionControl: false,
                    zoomControl: true,
                }).setView(PK_CENTER, 6);

                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    maxZoom: 18,
                }).addTo(map);

                stateRef.current = { L, map };
                placeMarkers(L, map, lawyers);
            } catch (e) {
                // silently ignore — map just won't render
            }
        };

        bootstrap();

        return () => {
            alive = false;
            if (stateRef.current) {
                stateRef.current.map.remove();
                stateRef.current = null;
            }
            markersRef.current = [];
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // ── refresh markers when lawyers list changes ──────────────────
    useEffect(() => {
        if (!stateRef.current) return;
        placeMarkers(stateRef.current.L, stateRef.current.map, lawyers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [lawyers]);

    // ── helpers ───────────────────────────────────────────────────
    function placeMarkers(L, map, list) {
        markersRef.current.forEach(m => m.remove());
        markersRef.current = [];

        const pins = list.filter(l => l.lat != null && l.lng != null);

        pins.forEach(l => {
            const fee    = l.fee ? `₨${l.fee.toLocaleString()}/hr` : 'Consult';
            const safeId = String(l._id || l.bar || Math.random()).replace(/[^a-zA-Z0-9]/g, '_');
            const cbKey  = `__lmap_${safeId}`;
            window[cbKey] = () => onSelect(l);

            const marker = L.marker([l.lat, l.lng], { icon: makeIcon(L, l.avail) })
                .addTo(map)
                .bindPopup(
                    `<div style="font-family:system-ui;min-width:170px;line-height:1.6">
                        <strong style="font-size:13px">${l.name}</strong><br>
                        <span style="color:#6b7280;font-size:11px">${l.spec}</span><br>
                        <span style="color:#6b7280;font-size:11px">${fee} &middot; ${l.city}</span><br>
                        <button onclick="window.${cbKey}()"
                            style="margin-top:8px;width:100%;padding:5px 0;background:#3b82f6;
                                   color:#fff;border:none;border-radius:6px;cursor:pointer;
                                   font-size:12px;font-weight:600">
                            View Profile
                        </button>
                    </div>`,
                    { maxWidth: 230 }
                );

            markersRef.current.push(marker);
        });

        if (pins.length > 1) {
            map.fitBounds(
                L.latLngBounds(pins.map(l => [l.lat, l.lng])),
                { padding: [50, 50], maxZoom: 10 }
            );
        } else if (pins.length === 1) {
            map.setView([pins[0].lat, pins[0].lng], 9);
        }
    }

    return <div ref={containerRef} style={{ height, width: '100%' }} />;
}
