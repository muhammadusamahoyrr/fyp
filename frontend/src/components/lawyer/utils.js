const PALETTE = ["#2C606E","#1A3A42","#3A7A8A","#4A6B5A","#3D5A6D","#2E7D6A","#4A5568","#2D6A6A"];
export const avatarBg = (initials = "") =>
  PALETTE[(initials.charCodeAt(0) || 0) % PALETTE.length];
