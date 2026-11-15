/**
 * A marca: a tela de um radar, com a varredura e um ponto detectado. `animated` gira a varredura
 * (só no login; com "reduzir movimento" o sistema a deixa parada).
 */
export function RadarMark({
  size = 28,
  animated = false,
  className = "",
}: {
  size?: number;
  animated?: boolean;
  className?: string;
}) {
  return (
    <svg
      aria-hidden
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      className={className}
    >
      <circle cx="24" cy="24" r="22" stroke="currentColor" strokeOpacity="0.35" strokeWidth="1.5" />
      <circle cx="24" cy="24" r="14" stroke="currentColor" strokeOpacity="0.3" strokeWidth="1.5" />
      <circle cx="24" cy="24" r="6" stroke="currentColor" strokeOpacity="0.3" strokeWidth="1.5" />
      <g
        className={animated ? "animate-varredura" : undefined}
        style={{ transformOrigin: "24px 24px" }}
      >
        <path d="M24 24 L24 2 A22 22 0 0 1 43.05 13 Z" fill="var(--color-sinal)" fillOpacity="0.28" />
        <path d="M24 24 L24 2" stroke="var(--color-sinal)" strokeWidth="2" strokeLinecap="round" />
      </g>
      <circle cx="33" cy="16" r="3.2" fill="var(--color-sinal)" />
    </svg>
  );
}
