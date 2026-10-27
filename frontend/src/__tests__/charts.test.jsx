import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LineChart from '../charts/LineChart.jsx';

const xs = Array.from({ length: 1001 }, (_, i) => i); // 0 … 1000 s
const series = [{ name: 'HR', unit: 'bpm', xs, ys: xs.map((x) => 100 + Math.sin(x / 30) * 20), color: 'red' }];
const fmt = (v) => `${Math.round(v)}s`;

function range() {
  return screen.getByText(/–|Drag across/).textContent;
}

describe('LineChart zoom and pan', () => {
  it('zooms in, moves along, zooms out and resets with the toolbar', async () => {
    render(<LineChart series={series} xFormat={fmt} title="HR" />);
    expect(range()).toBe('Drag across the chart to zoom');
    expect(screen.getByRole('button', { name: 'Reset' })).toBeDisabled();

    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(range()).toBe('188s – 813s'); // 1000 / 1.6 wide, centred
    await userEvent.click(screen.getByRole('button', { name: 'Move right' }));
    expect(range()).toBe('375s – 1000s'); // half a window right, stopped at the end
    expect(screen.getByRole('button', { name: 'Move right' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Move left' }));
    expect(range()).toBe('63s – 688s');

    await userEvent.click(screen.getByRole('button', { name: 'Zoom out' }));
    expect(range()).toBe('Drag across the chart to zoom'); // back to everything
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    await userEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(range()).toBe('Drag across the chart to zoom');
  });

  it('zooms to a dragged segment and resets with the 0 key', () => {
    render(<LineChart series={series} xFormat={fmt} title="HR" />);
    const svg = screen.getByRole('img', { name: /HR/ });
    svg.setPointerCapture = () => {};
    // Plot area: x from 46 px to 626 px (640 px wide) → 0 … 1000 s.
    fireEvent.pointerDown(svg, { button: 0, clientX: 46 + 58, pointerId: 1 });
    fireEvent.pointerMove(svg, { clientX: 46 + 290, pointerId: 1 });
    fireEvent.pointerUp(svg, { pointerId: 1 });
    expect(range()).toBe('100s – 500s');
    fireEvent.keyDown(svg, { key: '0' });
    expect(range()).toBe('Drag across the chart to zoom');
  });
});
