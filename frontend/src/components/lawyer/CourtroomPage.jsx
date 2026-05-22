'use client';
import { useRouter } from 'next/navigation';
import { useTheme } from './theme.js';
import { Icon, I } from './icons.jsx';

export function CourtroomPage() {
    const { t } = useTheme();
    const router = useRouter();

    const features = [
        { icon: I.gavel,     label: 'AI Judge',          desc: 'Intelligent presiding judge' },
        { icon: I.clients,   label: 'Live Proceedings',  desc: 'Real-time session flow' },
        { icon: I.courtroom, label: 'Formal Environment', desc: '3D courtroom simulation' },
        { icon: I.fileText,  label: 'Evidence Review',   desc: 'Document presentation' },
    ];

    return (
        <div style={{
            flex: 1, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center',
            padding: '40px 24px', gap: 28,
        }}>
            {/* Icon badge */}
            <div style={{
                width: 72, height: 72, borderRadius: 20,
                background: `${t.primary}18`,
                border: `1.5px solid ${t.primary}30`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
                <Icon d={I.courtroom} size={34} style={{ color: t.primary }} />
            </div>

            {/* Heading */}
            <div style={{ textAlign: 'center', maxWidth: 500 }}>
                <div style={{ fontSize: 22, fontWeight: 700, color: t.text, marginBottom: 8, letterSpacing: '0.01em' }}>
                    Courtroom Simulation
                </div>
                <div style={{ fontSize: 13.5, color: t.textMuted, lineHeight: 1.65 }}>
                    Enter the AI-powered 3D courtroom environment. Practice arguments,
                    conduct proceedings, and prepare for real court sessions in an
                    immersive legal simulation.
                </div>
            </div>

            {/* Feature grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12, width: '100%', maxWidth: 480 }}>
                {features.map(({ icon, label, desc }, i) => (
                    <div key={i} style={{
                        padding: '14px 16px', borderRadius: 10,
                        background: t.card, border: `1px solid ${t.border}`,
                        display: 'flex', alignItems: 'flex-start', gap: 12,
                    }}>
                        <div style={{
                            width: 34, height: 34, borderRadius: 9, flexShrink: 0,
                            background: `${t.primary}14`,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}>
                            <Icon d={icon} size={16} style={{ color: t.primary }} />
                        </div>
                        <div>
                            <div style={{ fontSize: 13, fontWeight: 650, color: t.text, lineHeight: 1.3 }}>{label}</div>
                            <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 2 }}>{desc}</div>
                        </div>
                    </div>
                ))}
            </div>

            {/* Launch button */}
            <button
                onClick={() => router.push('/courtroom/session')}
                style={{
                    padding: '13px 40px', borderRadius: 10,
                    border: 'none', background: t.primary,
                    color: '#fff', fontSize: 14.5, fontWeight: 700,
                    cursor: 'pointer', letterSpacing: '0.03em',
                    transition: 'opacity 0.15s, transform 0.12s',
                    boxShadow: `0 4px 16px ${t.primary}40`,
                }}
                onMouseEnter={e => { e.currentTarget.style.opacity = '0.88'; e.currentTarget.style.transform = 'translateY(-1px)'; }}
                onMouseLeave={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.transform = 'none'; }}
            >
                Launch Courtroom &nbsp;→
            </button>

            {/* Phase label */}
            <div style={{ fontSize: 11.5, color: t.textFaint, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                Phase 1 · 3D Environment · AI Integration Pending
            </div>
        </div>
    );
}
