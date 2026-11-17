'use client';

import { ButtonHTMLAttributes, forwardRef } from 'react';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'md' | 'lg' | 'xl';
}

const VARIANT_CLS: Record<NonNullable<Props['variant']>, string> = {
  primary: 'bg-warm-primary hover:bg-warm-dark text-white',
  secondary: 'bg-white hover:bg-warm-light text-warm-primary border-2 border-warm-primary',
  danger: 'bg-red-500 hover:bg-red-600 text-white',
  ghost: 'bg-transparent hover:bg-warm-light text-gray-700',
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
        className={`rounded-xl font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${VARIANT_CLS[variant]} ${SIZE_CLS[size]} ${className}`}
        {...rest}
      />
    );
  }
);
LargeButton.displayName = 'LargeButton';
