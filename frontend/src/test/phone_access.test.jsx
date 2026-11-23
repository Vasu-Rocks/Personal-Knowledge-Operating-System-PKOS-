import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import PhoneAccessSection from '../components/phone/PhoneAccessSection';

const NOW = new Date().toISOString();
const OFF = { enabled: false, running: false, port: null, addresses: [{ address: '192.168.137.1', name: 'Local Area Connection* 2', url: null, pairUrl: null }], fingerprint: null, error: null, pairing: null, devices: [] };
const ON = {
  enabled: true, running: true, port: 47100, error: null, pairing: null, devices: [],
  fingerprint: 'AB:CD:EF:12:34:56',
  addresses: [
    { address: '192.168.137.1', name: 'Local Area Connection* 2', url: 'https://192.168.137.1:47100', pairUrl: null },
    { address: '10.0.0.7', name: 'Wi-Fi', url: 'https://10.0.0.7:47100', pairUrl: null },
  ],
};
const PAIRING = {
  ...ON,
  pairing: { code: '482913', expiresAt: new Date(Date.now() + 299000).toISOString(), triesLeft: 5 },
  addresses: ON.addresses.map((a) => ({ ...a, pairUrl: `${a.url}/?pair=482913` })),
};
const PIXEL = { id: 'd1', name: 'Android phone · Chrome', pairedAt: NOW, lastSeenAt: NOW };

/** A fake desktop bridge; `script` maps a call name to the status it should return next. */
function fakeDesktop(initial, script = {}) {
  let current = initial;
  const step = (name, fallback) => vi.fn(async (...args) => {
    current = script[name] ? script[name](...args) : fallback(...args);
    return current;
  });
  const desktop = {
    isDesktop: true,
    phone: {
      status: vi.fn(async () => current),
      setEnabled: step('setEnabled', (enabled) => (enabled ? ON : OFF)),
      pair: step('pair', () => PAIRING),
      cancelPair: step('cancelPair', () => ON),
      remove: step('remove', () => ({ ...current, devices: [] })),
    },
    set: (s) => { current = s; },
  };
  return desktop;
}

describe('Phone access section', () => {
  it('is off by default and shows the addresses once switched on', async () => {
    const desktop = fakeDesktop(OFF);
    render(<PhoneAccessSection desktop={desktop} />);
    const box = await screen.findByRole('checkbox', { name: /Let paired phones on this network use PKOS/ });
    await waitFor(() => expect(box).toBeEnabled());
    expect(box).not.toBeChecked();
    expect(screen.queryByTestId('phone-addresses')).not.toBeInTheDocument();

    await userEvent.click(box);
    expect(desktop.phone.setEnabled).toHaveBeenCalledWith(true);
    const list = await screen.findByTestId('phone-addresses');
    expect(list).toHaveTextContent('https://192.168.137.1:47100 · Mobile hotspot');
    expect(list).toHaveTextContent('https://10.0.0.7:47100 · Wi-Fi');
    expect(list).toHaveTextContent('AB:CD:EF:12');
    expect(list).toHaveTextContent('not private');
  });

  it('switching off hides the addresses', async () => {
    const desktop = fakeDesktop(ON);
    render(<PhoneAccessSection desktop={desktop} />);
    await screen.findByTestId('phone-addresses');
    await userEvent.click(screen.getByRole('checkbox', { name: /Let paired phones/ }));
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

  it('"Pair a phone" shows a QR code, the 6-digit code and how long it is valid', async () => {
    const desktop = fakeDesktop(ON);
    render(<PhoneAccessSection desktop={desktop} />);
    await new Promise((r) => setTimeout(r, 1500)); // Settings open for a while before pairing (the countdown must not lag)
    await userEvent.click(await screen.findByRole('button', { name: /Pair a phone/ }));
    const panel = await screen.findByTestId('phone-pairing');
    const qr = within(panel).getByRole('img', { name: /QR code to pair a phone through Mobile hotspot/ });
    expect(qr.getAttribute('src')).toMatch(/^data:image\/gif;base64,/);
    expect(within(panel).getByLabelText('Pairing code')).toHaveTextContent('482 913');
    await waitFor(() => expect(panel).toHaveTextContent(/4:5\d left/)); // never more than the 5 minutes a code lasts

    // The QR code can point at the Wi-Fi address instead.
    const before = qr.getAttribute('src');
    await userEvent.selectOptions(within(panel).getByRole('combobox', { name: 'Network the phone uses' }), '10.0.0.7');
    expect(within(panel).getByRole('img', { name: /through Wi-Fi/ }).getAttribute('src')).not.toBe(before);

    await userEvent.click(within(panel).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByTestId('phone-pairing')).not.toBeInTheDocument());
    expect(desktop.phone.cancelPair).toHaveBeenCalled();
  });

  it('names the phone once it has paired, and lists paired phones with Remove', async () => {
    const desktop = fakeDesktop(ON);
    render(<PhoneAccessSection desktop={desktop} />);
    await userEvent.click(await screen.findByRole('button', { name: /Pair a phone/ }));
    await screen.findByTestId('phone-pairing');
    desktop.set({ ...ON, devices: [PIXEL] }); // the phone used the code
    expect(await screen.findByText(/Paired: Android phone · Chrome/, {}, { timeout: 4000 })).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Paired phones' });
    expect(list).toHaveTextContent('Android phone · Chrome');
    await userEvent.click(within(list).getByRole('button', { name: 'Remove Android phone · Chrome' }));
    expect(desktop.phone.remove).toHaveBeenCalledWith('d1');
    await waitFor(() => expect(screen.queryByRole('list', { name: 'Paired phones' })).not.toBeInTheDocument());
  });
});
