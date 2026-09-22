import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Tausender mit schmalem Leerzeichen — wie im alten Panel. */
export function fmtNum(n: number): string {
  return n.toLocaleString("de-DE").replace(/\./g, " ");
}
