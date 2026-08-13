import type { ButtonHTMLAttributes } from 'react';
import styles from './PixelButton.module.css';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'ghost' | 'danger' | 'success';
  size?: 'sm' | 'md';
}

/** Chunk-button with hard shadow and "key travel" press — the core 8-bit control. */
export function PixelButton({
  variant = 'ghost',
  size = 'md',
  className,
  ...rest
}: Props) {
  return (
    <button
      className={[styles.btn, styles[variant], styles[size], className ?? '']
        .filter(Boolean)
        .join(' ')}
      {...rest}
    />
  );
}
