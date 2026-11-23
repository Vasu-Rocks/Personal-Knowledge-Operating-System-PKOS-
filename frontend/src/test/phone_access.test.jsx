import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import PhoneAccessSection from '../components/phone/PhoneAccessSection';

const OFF = { enabled: false, running: false, port: null, addresses: [{ address: '192.168.137.1', name: 'Local Area Connection* 2', url: null }], fingerprint: null, error: null };
const ON = {
  enabled: true, running: true, port: 47100, error: null,
  fingerprint: 'AB:CD:EF:12:34:56',
  addresses: [
    { address: '192.168.137.1', name: 'Local Area Connection* 2', url: 'https://192.168.137.1:47100' },
    { address: '10.0.0.7', name: 'Wi-Fi', url: 'https://10.0.0.7:47100' },
  ],
};

function fakeDesktop(initial, { onSet } = {}) {
  let current = initial;
  return {
    isDesktop: true,
    phone: {
      status: vi.fn(async () => current),
      setEnabled: vi.fn(async (enabled) => {
        current = onSet ? onSet(enabled) : (enabled ? ON : OFF);
        return current;
      }),
    },
  };
}

describe('Phone access section', () => {
  it('is off by default and shows the addresses once switched on', async () => {
    const desktop = fakeDesktop(OFF);
    render(<PhoneAccessSection desktop={desktop} />);
    const box = await screen.findByRole('checkbox', { name: /Let phones on this network use PKOS/ });
    await waitFor(() => expect(box).toBeEnabled());
    expect(box).not.toBeChecked();
    expect(screen.queryByTestId('phone-addresses')).not.toBeInTheDocument();

    await userEvent.click(box);
    expect(desktop.phone.setEnabled).toHaveBeenCalledWith(true);
    const list = await screen.findByTestId('phone-addresses');
    expect(list).toHaveTextContent('https://192.168.137.1:47100 · Mobile hotspot');
    expect(list).toHaveTextContent('https://10.0.0.7:47100 · Wi-Fi');
    expect(list).toHaveTextContent('AB:CD:EF:12');           // the certificate code to compare on the phone
    expect(list).toHaveTextContent('not private');           // the expected warning is explained
  });

  it('switching off hides the addresses', async () => {
    const desktop = fakeDesktop(ON);
    render(<PhoneAccessSection desktop={desktop} />);
    await screen.findByTestId('phone-addresses');
    await userEvent.click(screen.getByRole('checkbox', { name: /Let phones/ }));
    expect(desktop.phone.setEnabled).toHaveBeenCalledWith(false);
    await waitFor(() => expect(screen.queryByTestId('phone-addresses')).not.toBeInTheDocument());
  });

  it('says what to do when the laptop is not on a network, and shows errors', async () => {
    const { unmount } = render(<PhoneAccessSection desktop={fakeDesktop({ ...ON, addresses: [] })} />);
    expect(await screen.findByRole('status')).toHaveTextContent('Turn on Mobile hotspot');
    unmount();
    render(<PhoneAccessSection desktop={fakeDesktop({ ...OFF, enabled: true, error: 'Another program is using the port for phone access.' })} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Another program is using the port');
  });
});
