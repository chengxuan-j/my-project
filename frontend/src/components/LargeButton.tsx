'use client';

import { ButtonHTMLAttributes, forwardRef } from 'react';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'md' | 'lg' | 'xl';
}

const VARIANT_CLS: Record<NonNullable<Props['variant']>, string> = {
  primary: 'bg-primary hover:bg-primary-strong text-on-primary shadow-btn',
  secondary:
    'bg-card hover:bg-primary-soft text-primary border border-hairline-strong',
  danger: 'bg-danger hover:bg-danger/90 text-on-primary',
  ghost: 'bg-transparent hover:bg-primary-soft text-muted',
};

const SIZE_CLS: Record<NonNullable<Props['size']>, string> = {
  md: 'min-h-[48px] px-4 text-base',
  lg: 'min-h-[56px] px-6 text-lg',
  xl: 'min-h-[72px] px-8 text-xl font-bold',
};

export const LargeButton = forwardRef<HTMLButtonElement, Props>(
  ({ variant = 'primary', size = 'md', className = '', ...rest }, ref) => {
    return (
      <button
        ref={ref}
        className={`rounded-btn inline-flex items-center justify-center gap-1.5 font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${VARIANT_CLS[variant]} ${SIZE_CLS[size]} ${className}`}
        {...rest}
      />
    );
  }
);
LargeButton.displayName = 'LargeButton';
