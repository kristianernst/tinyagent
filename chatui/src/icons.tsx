import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & {
  size?: number;
  d?: string;
  fill?: string;
  stroke?: string;
  strokeWidth?: number;
  children?: React.ReactNode;
};

export const Icon = ({
  d,
  size = 16,
  fill = "none",
  stroke = "currentColor",
  strokeWidth = 1.5,
  children,
  ...props
}: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill={fill}
    stroke={stroke}
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
    {...props}
  >
    {d ? <path d={d} /> : children}
  </svg>
);

export const IconCheck = (p: IconProps) => <Icon d="M3.5 8.5 L6.5 11.5 L12.5 5" {...p} />;
export const IconChev = (p: IconProps) => <Icon d="M3.5 6 L8 10.5 L12.5 6" {...p} />;
export const IconChevR = (p: IconProps) => <Icon d="M6 3.5 L10.5 8 L6 12.5" {...p} />;
export const IconSearch = (p: IconProps) => (
  <Icon size={13} {...p}>
    <circle cx="7" cy="7" r="4.5" />
    <path d="M10.5 10.5 L13.5 13.5" />
  </Icon>
);
export const IconChart = (p: IconProps) => (
  <Icon size={18} {...p}>
    <path d="M2 11 C 3.5 11, 4 5, 5.5 5 S 7.5 11, 9 11 S 11 5, 12.5 5 S 14 9, 15 9" strokeWidth={1.7} />
  </Icon>
);
export const IconDoc = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 2 H10 L13 5 V14 H4 Z" />
    <path d="M10 2 V5 H13" />
  </Icon>
);
export const IconCode = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5.5 5 L2.5 8 L5.5 11" />
    <path d="M10.5 5 L13.5 8 L10.5 11" />
  </Icon>
);
export const IconDb = (p: IconProps) => (
  <Icon {...p}>
    <ellipse cx="8" cy="3.5" rx="5" ry="1.8" />
    <path d="M3 3.5 V8 C3 9, 5.2 9.8, 8 9.8 S13 9, 13 8 V3.5" />
    <path d="M3 8 V12.5 C3 13.5, 5.2 14.3, 8 14.3 S13 13.5, 13 12.5 V8" />
  </Icon>
);
export const IconWeb = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="8" cy="8" r="5.5" />
    <path d="M2.5 8 H13.5" />
    <path d="M8 2.5 C 10 4.5, 10 11.5, 8 13.5 C 6 11.5, 6 4.5, 8 2.5" />
  </Icon>
);
export const IconTerminal = (p: IconProps) => (
  <Icon {...p}>
    <rect x="2" y="3" width="12" height="10" rx="1.5" />
    <path d="M4.5 6.5 L6.5 8.5 L4.5 10.5" />
    <path d="M8.5 10.5 H11.5" />
  </Icon>
);
export const IconPlus = (p: IconProps) => <Icon d="M8 3 V13 M3 8 H13" {...p} />;
export const IconMic = (p: IconProps) => (
  <Icon {...p}>
    <rect x="6" y="2" width="4" height="8" rx="2" />
    <path d="M3.5 8 C3.5 11, 5.5 12.5, 8 12.5 S 12.5 11, 12.5 8" />
    <path d="M8 12.5 V14.5" />
  </Icon>
);
export const IconArrowUp = (p: IconProps) => <Icon d="M8 12.5 V3.5 M4 7.5 L8 3.5 L12 7.5" {...p} />;
export const IconStop = (p: IconProps) => (
  <Icon size={12} stroke="none" fill="currentColor" {...p}>
    <rect x="3" y="3" width="10" height="10" rx="2" />
  </Icon>
);
export const IconSidebarL = (p: IconProps) => (
  <Icon {...p}>
    <rect x="2" y="3" width="12" height="10" rx="2" />
    <path d="M6 3 V13" />
  </Icon>
);
export const IconSidebarR = (p: IconProps) => (
  <Icon {...p}>
    <rect x="2" y="3" width="12" height="10" rx="2" />
    <path d="M10 3 V13" />
  </Icon>
);
export const IconFolder = (p: IconProps) => (
  <Icon {...p}>
    <path d="M2 5 V12 C2 12.6, 2.4 13, 3 13 H13 C13.6 13, 14 12.6, 14 12 V6 C14 5.4, 13.6 5, 13 5 H8 L6.5 3.5 H3 C2.4 3.5, 2 4, 2 4.5 Z" />
  </Icon>
);
export const IconSettings = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="8" cy="8" r="2" />
    <path d="M8 1.5 V3 M8 13 V14.5 M14.5 8 H13 M3 8 H1.5 M12.6 3.4 L11.5 4.5 M4.5 11.5 L3.4 12.6 M12.6 12.6 L11.5 11.5 M4.5 4.5 L3.4 3.4" />
  </Icon>
);
export const IconFile = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 2 H10 L13 5 V14 H4 Z" />
    <path d="M10 2 V5 H13" />
  </Icon>
);
export const IconImage = (p: IconProps) => (
  <Icon {...p}>
    <rect x="2" y="3" width="12" height="10" rx="1.5" />
    <circle cx="6" cy="7" r="1.2" />
    <path d="M3 12 L6.5 8.5 L9 11 L11 9 L13 11" />
  </Icon>
);
export const IconBolt = (p: IconProps) => (
  <Icon {...p}>
    <path d="M9 2 L4 9 H8 L7 14 L12 7 H8 Z" />
  </Icon>
);
export const IconChartArt = (p: IconProps) => (
  <Icon {...p}>
    <rect x="2" y="3" width="12" height="10" rx="1.5" />
    <path d="M4 10 C 5 10, 5.5 6, 7 6 S 8.5 10, 10 10 S 11.5 7, 12 7" />
  </Icon>
);
export const IconYolo = (p: IconProps) => (
  <Icon {...p}>
    <path d="M9 1.5 L3.5 9 H7.5 L6.5 14.5 L12.5 7 H8.5 Z" />
  </Icon>
);
export const IconAuto = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="8" cy="8" r="5.5" />
    <path d="M5 8 L7 10 L11 6" />
  </Icon>
);
export const IconAsk = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5.5 6 C5.5 4, 7 3, 8 3 C9.5 3, 10.8 4, 10.8 5.5 C10.8 7, 9.5 7.5, 8 8.5 V10" />
    <circle cx="8" cy="12.5" r="0.6" fill="currentColor" stroke="none" />
  </Icon>
);
export const IconMaximize = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 6 V3 H6 M10 3 H13 V6 M13 10 V13 H10 M6 13 H3 V10" />
  </Icon>
);
