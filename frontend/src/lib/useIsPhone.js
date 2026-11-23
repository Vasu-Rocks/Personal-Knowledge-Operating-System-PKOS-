import { useEffect, useState } from 'react';

// Phone layout below this width (docs/08_PHONE_ACCESS_PLAN.md, step P3). The same build serves laptop and phone.
export const PHONE_QUERY = '(max-width: 767px)';

function matches() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(PHONE_QUERY).matches;
}

/** True on a phone-sized screen; follows rotation and window resizing. */
export default function useIsPhone() {
  const [isPhone, setIsPhone] = useState(matches);
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined;
    const query = window.matchMedia(PHONE_QUERY);
    const onChange = () => setIsPhone(query.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);
  return isPhone;
}
