const P: Record<string, string> = {
  grid: '<rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="7" rx="2"/><rect x="4" y="13" width="7" height="7" rx="2"/><rect x="13" y="13" width="7" height="7" rx="2"/>',
  finger: '<path d="M12 4a7 7 0 0 0-7 7v2"/><path d="M19 11a7 7 0 0 0-3-5.7"/><path d="M9 20c1-2 1.5-4 1.5-7a1.5 1.5 0 0 1 3 0c0 2.5-.3 4.7-1.3 7"/><path d="M15.5 19c.6-1.8 1-3.8 1-6"/><path d="M7 16.5c.5-1.2.5-2.3.5-3.5a4.5 4.5 0 0 1 9 0"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14c2.8 0 5 2.2 5 5"/>',
  device: '<rect x="6" y="3" width="12" height="18" rx="2.5"/><rect x="9" y="6" width="6" height="5" rx="1"/><circle cx="12" cy="16" r="2"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M21 20H3"/>',
  cog: '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
  logout: '<path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4"/><path d="M15 16l4-4-4-4M19 12H9"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
  left: '<path d="M12 6l-6 6 6 6M18 6l-6 6 6 6"/>',
  right: '<path d="M12 6l6 6-6 6M6 6l6 6-6 6"/>',
  up: '<path d="M12 18V6M7 11l5-5 5 5"/>',
  down: '<path d="M12 6v12M7 13l5 5 5-5"/>',
  helmet: '<path d="M4 16a8 8 0 0 1 16 0"/><path d="M3 16h18v2H3z"/><path d="M12 8v5"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
};
export default function Icon({ name, size = 20, color = "currentColor", stroke = 1.7 }: { name: keyof typeof P | string; size?: number; color?: string; stroke?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" dangerouslySetInnerHTML={{ __html: P[name] ?? "" }} />;
}
