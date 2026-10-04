import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import App from './App';

describe('workspace shell', () => {
  it('renders sidebar and composer', () => {
    render(<App />);
    expect(screen.getByText('MTRINI')).toBeTruthy();
    expect(screen.getAllByText('New thread').length).toBeGreaterThan(0);
    expect(screen.getByPlaceholderText(/follow-up/i)).toBeTruthy();
  });

  it('opens the command menu on Ctrl+K', () => {
    render(<App />);
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(screen.getByPlaceholderText(/command, thread/i)).toBeTruthy();
  });
});
