// Pixel mascots, in the language of the Mtrini camel. Each is a 12x12 sprite:
//   X body (the bot's colour)   x shade (the same colour, darker)   o light   y warm accent   . nothing
// Eyes are holes: the dark tile shows through.
export const MASCOTS: Record<string, string[]> = {
  camel: [
    '........XX..',
    '.......XXXX.',
    '.......X.XXo',
    '.......XXXXo',
    '...XX..XXX..',
    '..XXXX.XXX..',
    '.XXXXXXXXX..',
    'XXXXXXXXXX..',
    'XXXXXXXXXX..',
    'xXXXXXXXXX..',
    '.XX....XX...',
    '.xx....xx...',
  ],
  fennec: [
    'XX........XX',
    'XoX......XoX',
    'XoXX....XXoX',
    'XooXXXXXXooX',
    'XXXXXXXXXXXX',
    'XXXXXXXXXXXX',
    'XX..XXXX..XX',
    'XX..XXXX..XX',
    'oXXXXooXXXXo',
    '.oXXo..oXXo.',
    '..ooXooXoo..',
    '....oooo....',
  ],
  owl: [
    'X..........X',
    'XX........XX',
    'XXXXXXXXXXXX',
    'XooooXXooooX',
    'Xo..oXXo..oX',
    'Xo..oXXo..oX',
    'XooooyyooooX',
    'XXXXXyyXXXXX',
    'XXoXXXXXXoXX',
    'XXXoXXXXoXXX',
    '.XXXXXXXXXX.',
    '..yy....yy..',
  ],
  stork: [
    '...XXXX.....',
    '..XXXXXX....',
    '..X.XXXXyyyy',
    '..XXXXXXyy..',
    '...XXXX.....',
    '..oooooo....',
    '.oooooooo...',
    '.ooooooxxx..',
    '.oooooxxxx..',
    '..ooooxx....',
    '....y.y.....',
    '...yy.yy....',
  ],
  cat: [
    'X..........X',
    'XX........XX',
    'XoX......XoX',
    'XXXXXXXXXXXX',
    'XXXXXXXXXXXX',
    'X..XXXXXX..X',
    'X..XXXXXX..X',
    'XXXXXooXXXXX',
    'oXXXo..oXXXo',
    'XXXXXooXXXXX',
    '.XXXXXXXXXX.',
    '...XXXXXX...',
  ],
  tortoise: [
    '............',
    '............',
    '...xxxxx....',
    '..xXxXxXx...',
    '.xXxXxXxXx..',
    '.xxXxXxXxx.X',
    'xxxxxxxxxxXX',
    'oooooooooX.X',
    '.oo....ooXXX',
    '.oo....oo...',
    '............',
    '............',
  ],
  parrot: [
    '....XXXX....',
    '...XXXXXX...',
    '...XX.XXyy..',
    '...XXXXXyyy.',
    '...XXXXX.yy.',
    '..XXXXXX....',
    '.XXxxXXX....',
    '.XxxxXXX....',
    '.XxxxXX.....',
    '..xxXX......',
    '..x.yy......',
    '.x..........',
  ],
  beetle: [
    '..x......x..',
    '...x....x...',
    '....XXXX....',
    '...X.XX.X...',
    'x.XXXXXXXX.x',
    '.xXXXxxXXXx.',
    '..XXXxxXXX..',
    'xxXXXxxXXXxx',
    '..XXXxxXXX..',
    '.xXXXxxXXXx.',
    'x..XXxxXX..x',
    '....XxxX....',
  ],
  bee: [
    '............',
    '..oo....oo..',
    '.oooo..oooo.',
    '.oooo..oooo.',
    '..ooXXXXoo..',
    '...XXXXXX...',
    '..XX.XX.XX..',
    '..XXXXXXXX..',
    '..yyyyyyyy..',
    '..XXXXXXXX..',
    '...yyyyyy...',
    '....XXXX....',
  ],
  gecko: [
    '....XXXX....',
    '...X.XX.X...',
    '...XXXXXX...',
    'X...XXXX...X',
    '.XXXXXXXXXX.',
    '....XXXX....',
    '....XXXX....',
    '.XXXXXXXXXX.',
    'X...XXXX...X',
    '.....XXX....',
    '......XXx...',
    '.......xx...',
  ],
};

export const MASCOT_NAMES = Object.keys(MASCOTS);

export function shade(hex: string, k = 0.62): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return '#3a7f8c';
  const n = parseInt(m[1], 16);
  const part = (s: number) => Math.round(((n >> s) & 255) * k).toString(16).padStart(2, '0');
  return `#${part(16)}${part(8)}${part(0)}`;
}

// The coloured cells of a mascot: [x, y, fill].
export function cells(mascot: string, color: string, paused = false): [number, number, string][] {
  const rows = MASCOTS[mascot] || MASCOTS.camel;
  const body = paused ? '#8a8f98' : color || '#5ad1e6';
  const fill: Record<string, string> = { X: body, x: shade(body), o: paused ? '#c9ccd2' : '#f5efe2', y: paused ? '#a3a7ae' : '#f2b84b' };
  const out: [number, number, string][] = [];
  rows.forEach((row, y) => { for (let x = 0; x < row.length; x++) if (fill[row[x]]) out.push([x, y, fill[row[x]]]); });
  return out;
}
