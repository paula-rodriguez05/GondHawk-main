import { useState } from 'react';
import { Globe, Router, Network, Server, Monitor, Cctv, Laptop } from 'lucide-react';

// Topología modelada en Cisco Packet Tracer (proyecto integrador).
// Datos tomados de la configuración real de Router0 (R-TIENDA) y Switch1 (SW-TIENDA).
const VLANS = {
  10: { nombre: 'Clientes', color: '#C9B79C' },
  20: { nombre: 'Servidores', color: '#D9A066' },
  30: { nombre: 'Cámaras IoT', color: '#8FB573' },
  40: { nombre: 'Invitados', color: '#B98A5E' },
  99: { nombre: 'Gestión', color: '#C86A50' },
};

const W = 640;
const H = 250;

const CORE = [
  { id: 'server1', x: 52, y: 125, icon: Globe, nombre: 'Server1', detalle: 'DNS · 8.8.8.8' },
  { id: 'router1', x: 160, y: 125, icon: Router, nombre: 'Router1', detalle: 'Cisco 2901 · 203.0.113.1' },
  { id: 'router0', x: 275, y: 125, icon: Router, nombre: 'Router0', detalle: 'Cisco 2901 · NAT · 203.0.113.2' },
  { id: 'switch1', x: 395, y: 125, icon: Network, nombre: 'Switch1', detalle: '2960-24TT · 192.168.99.2', vlan: 99 },
];

const HOSTS = [
  { id: 'pc3', y: 22, icon: Monitor, nombre: 'PC3', detalle: '192.168.10.12', vlan: 10 },
  { id: 'pc2', y: 63, icon: Monitor, nombre: 'PC2', detalle: '192.168.10.11', vlan: 10 },
  { id: 'server0', y: 104, icon: Server, nombre: 'Server0', detalle: '192.168.20.10', vlan: 20 },
  { id: 'iot0', y: 145, icon: Cctv, nombre: 'IoT0', detalle: '192.168.30.12', vlan: 30 },
  { id: 'iot1', y: 186, icon: Cctv, nombre: 'IoT1', detalle: '192.168.30.11', vlan: 30 },
  { id: 'laptop0', y: 227, icon: Laptop, nombre: 'Laptop0', detalle: '192.168.40.11', vlan: 40 },
].map((h) => ({ ...h, x: 528 }));

const SW = CORE[3];
const CORE_LINKS = [
  { a: CORE[0], b: CORE[1], label: '8.8.8.0/24' },
  { a: CORE[1], b: CORE[2], label: '203.0.113.0/30' },
  { a: CORE[2], b: CORE[3], label: 'troncal 802.1Q' },
];

function curve(a, b) {
  const mx = (a.x + b.x) / 2;
  return `M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`;
}

function Node({ n, onHover, activo }) {
  const Icon = n.icon;
  const color = n.vlan ? VLANS[n.vlan].color : 'var(--beige)';
  return (
    <g
      onMouseEnter={() => onHover(n)}
      onMouseLeave={() => onHover(null)}
      style={{ cursor: 'default' }}
    >
      <circle cx={n.x} cy={n.y} r={activo ? 17 : 15} fill="#1d1510" stroke={color} strokeWidth="1.8" style={{ transition: 'r .15s' }} />
      <Icon x={n.x - 8} y={n.y - 8} width={16} height={16} color="var(--marfil)" strokeWidth={1.8} />
    </g>
  );
}

export function NetworkPanel() {
  const [hover, setHover] = useState(null);

  return (
    <div className="rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] relative flex flex-col" style={{ minHeight: '250px' }}>
      <div className="flex items-center justify-between gap-2 border-b border-[var(--panel-border)] px-3 py-1.5">
        <h3 className="text-sm font-medium">Red de la tienda</h3>
        <div className="flex items-center gap-1.5 text-[12px] text-[var(--ink-muted)]">
          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-[var(--background)]">
            <span className="w-1 h-1 rounded-full bg-emerald-500 animate-pulse" />
            Operativa
          </span>
          <span>5 VLAN</span>
          <span>· 10 equipos</span>
        </div>
      </div>

      <div className="m-2 flex-1 rounded-md" style={{ background: 'var(--background, #000)', minHeight: 0 }}>
        <svg width="100%" height="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" className="w-full h-full">

          {/* Zona LAN de la tienda */}
          <rect x="235" y="8" width="397" height="234" rx="10" fill="none" stroke="rgba(237,228,211,.14)" strokeDasharray="4 4" />
          <text x="243" y="22" fontSize="9" fill="rgba(237,228,211,.45)" letterSpacing=".08em">LAN TIENDA · 192.168.0.0/16</text>
          <text x="20" y="22" fontSize="9" fill="rgba(237,228,211,.45)" letterSpacing=".08em">WAN</text>

          {/* Enlaces del núcleo */}
          {CORE_LINKS.map((l) => (
            <g key={l.label}>
              <path id={`ln-${l.a.id}`} d={`M ${l.a.x} ${l.a.y} L ${l.b.x} ${l.b.y}`} stroke="rgba(237,228,211,.55)" strokeWidth="1.6" />
              <text x={(l.a.x + l.b.x) / 2} y={l.a.y - 24} textAnchor="middle" fontSize="9" fill="rgba(237,228,211,.6)">{l.label}</text>
            </g>
          ))}

          {/* Enlaces de acceso por VLAN */}
          {HOSTS.map((h) => {
            const c = VLANS[h.vlan].color;
            const atenuado = hover && hover.vlan && hover.vlan !== h.vlan;
            return (
              <path
                key={h.id}
                id={`acc-${h.id}`}
                d={curve(SW, h)}
                fill="none"
                stroke={c}
                strokeWidth="1.6"
                opacity={atenuado ? 0.2 : 0.85}
                style={{ transition: 'opacity .2s' }}
              />
            );
          })}

          {/* Tráfico: cámaras → servidor y clientes → tablero */}
          {[
            { path: 'acc-iot0', color: VLANS[30].color, dur: '2.4s' },
            { path: 'acc-iot1', color: VLANS[30].color, dur: '2.9s' },
            { path: 'acc-server0', color: VLANS[20].color, dur: '2.2s', reverse: true },
            { path: 'acc-pc2', color: VLANS[10].color, dur: '3.1s', reverse: true },
          ].map((p) => (
            <circle key={p.path} r="2.6" fill={p.color}>
              <animateMotion dur={p.dur} repeatCount="indefinite" keyPoints={p.reverse ? '0;1' : '1;0'} keyTimes="0;1" calcMode="linear">
                <mpath href={`#${p.path}`} />
              </animateMotion>
            </circle>
          ))}
          <circle r="2.6" fill="var(--beige)">
            <animateMotion dur="3.4s" repeatCount="indefinite" path={`M ${CORE[2].x} ${CORE[2].y} L ${CORE[0].x} ${CORE[0].y}`} />
          </circle>

          {[...CORE, ...HOSTS].map((n) => (
            <Node key={n.id} n={n} onHover={setHover} activo={hover?.id === n.id} />
          ))}

          {/* Etiquetas */}
          {CORE.map((n) => (
            <g key={`t-${n.id}`}>
              <text x={n.x} y={n.y + 31} textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--marfil)">{n.nombre}</text>
              <text x={n.x} y={n.y + 44} textAnchor="middle" fontSize="8.5" fill="rgba(237,228,211,.6)">{n.detalle.split(' · ')[0]}</text>
            </g>
          ))}
          {HOSTS.map((h) => (
            <g key={`t-${h.id}`}>
              <text x={h.x + 22} y={h.y - 1} fontSize="10.5" fontWeight="600" fill="var(--marfil)">{h.nombre}</text>
              <text x={h.x + 22} y={h.y + 10} fontSize="8.5" fill="rgba(237,228,211,.6)">{h.detalle}</text>
            </g>
          ))}

          {/* Leyenda VLAN */}
          <g transform="translate(18 206)">
            {Object.entries(VLANS).map(([id, v], i) => (
              <g key={id} transform={`translate(${(i % 2) * 96} ${Math.floor(i / 2) * 13})`}>
                <circle cx="4" cy="-3" r="3.2" fill={v.color} />
                <text x="11" y="0" fontSize="8.5" fill="rgba(237,228,211,.75)">{id} · {v.nombre}</text>
              </g>
            ))}
          </g>

          {/* Detalle al pasar el mouse */}
          {hover && (
            <g transform="translate(14 32)">
              <rect width="200" height="40" rx="7" fill="#1d1510" stroke="rgba(237,228,211,.25)" />
              <text x="10" y="16" fontSize="10.5" fontWeight="600" fill="var(--marfil)">
                {hover.nombre}{hover.vlan ? ` · VLAN ${hover.vlan}` : ''}
              </text>
              <text x="10" y="30" fontSize="9" fill="rgba(237,228,211,.7)">{hover.detalle}</text>
            </g>
          )}
        </svg>
      </div>
    </div>
  );
}
