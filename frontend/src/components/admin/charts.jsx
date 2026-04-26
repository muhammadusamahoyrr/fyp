'use client';

export const BarChart = ({ data, labels, colors, T }) => {
  const maxVal = Math.max(...data.flat());
  const h = 160;
  const barW = Math.floor(320 / (data.length * 2 + 1));
  return (
    <svg width="100%" height={h} viewBox={`0 0 320 ${h}`} preserveAspectRatio="none">
      {data.map((group, gi) => group.map((val, si) => {
        const bh = (val / maxVal) * (h - 20);
        const x = gi * (barW * 2 + 4) + si * (barW + 2) + 8;
        return (
          <rect key={`${gi}-${si}`} x={x} y={h - bh - 16} width={barW} height={bh}
            rx={3} fill={colors[si] || colors[0]} opacity={0.85} />
        );
      }))}
      {labels.map((l, i) => (
        <text key={i} x={i * (barW * 2 + 4) + barW + 8} y={h - 2}
          textAnchor="middle" fontSize={9} fill={T.textFaint}>{l}</text>
      ))}
    </svg>
  );
};

export const DonutChart = ({ segments, T, onSegmentClick }) => {
  const total = segments.reduce((s, seg) => s + seg.value, 0);
  let startAngle = -Math.PI / 2;
  const cx = 80, cy = 80, r = 60, iR = 38;
  const slices = segments.map(seg => {
    const angle = (seg.value / total) * 2 * Math.PI;
    const x1 = cx + r * Math.cos(startAngle), y1 = cy + r * Math.sin(startAngle);
    startAngle += angle;
    const x2 = cx + r * Math.cos(startAngle), y2 = cy + r * Math.sin(startAngle);
    const ix1 = cx + iR * Math.cos(startAngle - angle), iy1 = cy + iR * Math.sin(startAngle - angle);
    const ix2 = cx + iR * Math.cos(startAngle), iy2 = cy + iR * Math.sin(startAngle);
    const large = angle > Math.PI ? 1 : 0;
    return { ...seg, d: `M${x1},${y1} A${r},${r} 0 ${large},1 ${x2},${y2} L${ix2},${iy2} A${iR},${iR} 0 ${large},0 ${ix1},${iy1} Z` };
  });
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
      <svg width={160} height={160} viewBox="0 0 160 160" style={{ flexShrink: 0 }}>
        {slices.map((s, i) => (
          <path key={i} d={s.d} fill={s.color} opacity={0.9} style={{ cursor: onSegmentClick ? "pointer" : "default" }}
            onClick={onSegmentClick} />
        ))}
        <text x={cx} y={cy - 6} textAnchor="middle" fontSize={22} fontWeight={700} fill={T.text}>{total}</text>
        <text x={cx} y={cy + 14} textAnchor="middle" fontSize={10} fill={T.textMuted}>Total</text>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {segments.map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: s.color, flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: T.textMuted }}>{s.label}</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: T.text, marginLeft: "auto" }}>{s.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
