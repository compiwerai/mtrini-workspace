import React from 'react';

// Minimal 14px stroke icon set — professional chrome, no emoji.
function base(props: React.SVGProps<SVGSVGElement> | undefined, ...kids: React.ReactNode[]) {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor"
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {kids}
    </svg>
  );
}

export const I = {
  folder: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <path key="a" d="M1.5 4.5c0-.8.7-1.5 1.5-1.5h3l1.2 1.5H13c.8 0 1.5.7 1.5 1.5v5c0 .8-.7 1.5-1.5 1.5h-10c-.8 0-1.5-.7-1.5-1.5v-6.5z" />),
  file: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <path key="a" d="M4 1.5h5.5L12.5 4.5V14.5h-8.5V1.5z" />, <path key="b" d="M9.5 1.5v3h3" />),
  plus: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <path key="a" d="M8 2.5v11M2.5 8h11" />),
  clock: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <circle key="a" cx="8" cy="8" r="6.2" />, <path key="b" d="M8 4.8V8l2.2 1.4" />),
  spark: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <path key="a" d="M8 1.8l1.7 4.5 4.5 1.7-4.5 1.7L8 14.2l-1.7-4.5L1.8 8l4.5-1.7L8 1.8z" />),
  gear: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <circle key="a" cx="8" cy="8" r="2.2" />,
    <path key="b" d="M8 1.8v1.8M8 12.4v1.8M1.8 8h1.8M12.4 8h1.8M3.6 3.6l1.3 1.3M11.1 11.1l1.3 1.3M12.4 3.6l-1.3 1.3M4.9 11.1l-1.3 1.3" />),
  branch: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <circle key="a" cx="4.5" cy="4" r="1.8" />, <circle key="b" cx="4.5" cy="12" r="1.8" />,
    <circle key="c" cx="11.5" cy="8" r="1.8" />,
    <path key="d" d="M4.5 5.8v4.4M6 4.5c2.5 0 1.5 3 4 3.2" />),
  search: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <circle key="a" cx="7" cy="7" r="4.5" />, <path key="b" d="M10.5 10.5L14.5 14.5" />),
  x: (p?: React.SVGProps<SVGSVGElement>) => base(p, <path key="a" d="M3.5 3.5l9 9M12.5 3.5l-9 9" />),
  check: (p?: React.SVGProps<SVGSVGElement>) => base(p, <path key="a" d="M2.5 8.5l3.5 3.5 7-8" />),
  pencil: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <path key="a" d="M11 2.5l2.5 2.5L5.5 13H3v-2.5l8-8z" />),
  trash: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <path key="a" d="M2.5 4h11M6.5 2.5h3M4 4l.7 10.5h6.6L12 4M6.8 7v4.5M9.2 7v4.5" />),
  send: (p?: React.SVGProps<SVGSVGElement>) => base(p, <path key="a" d="M8 13.5V2.5M3.5 7L8 2.5l4.5 4.5" />),
  stop: (p?: React.SVGProps<SVGSVGElement>) => base(p, <rect key="a" x="4" y="4" width="8" height="8" rx="1.5" fill="currentColor" stroke="none" />),
  refresh: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <path key="a" d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 1.8v2.7h-2.7" />),
  chev: (p?: React.SVGProps<SVGSVGElement>) => base(p, <path key="a" d="M6 3.5L10.5 8 6 12.5" />),
  terminal: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <rect key="a" x="1.5" y="3" width="13" height="10" rx="1.5" />, <path key="b" d="M4.5 6.5l2 1.5-2 1.5M7.5 10.5H11" />),
  command: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <path key="a" d="M5.5 5.5c-1.4 0-2.5 1-2.5 2.5s1.1 2.5 2.5 2.5h1v1c0 1.4 1 2.5 2.5 2.5s2.5-1.1 2.5-2.5-1-2.5-2.5-2.5h-1v-1c0-1.4-1-2.5-2.5-2.5z" />),
  box: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <rect key="a" x="2" y="2" width="12" height="12" rx="2" />),
  copy: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <rect key="a" x="5.5" y="5.5" width="8" height="8" rx="1.5" />, <path key="b" d="M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2" />),
  dot: (p?: React.SVGProps<SVGSVGElement>) => base(p, <circle key="a" cx="8" cy="8" r="3.5" fill="currentColor" stroke="none" />),
  open: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <path key="a" d="M6.5 3.5H3.5v9h9V9.5M9 2.5h5.5V8M14 2.5L7.5 9" />),
  image: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <rect key="a" x="1.8" y="2.8" width="12.4" height="10.4" rx="1.8" />,
    <circle key="b" cx="5.4" cy="6.4" r="1.3" />,
    <path key="c" d="M2.5 11.5l3.2-3.2 2.4 2.4 2.6-2.6 2.8 2.8" />),
  plug: (p?: React.SVGProps<SVGSVGElement>) => base(p,
    <path key="a" d="M5.5 2.5v3M10.5 2.5v3M4 5.5h8v2.5a4 4 0 0 1-8 0V5.5zM8 12v2.5" />),
};
