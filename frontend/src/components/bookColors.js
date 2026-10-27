// Shared by the Connections modal and the Knowledge Map: the same book always gets the same colour.
// Hues chosen to stay distinguishable on the dark background (no two greens/teals).
export const BOOK_COLORS = ['#3b82f6', '#f59e0b', '#10b981', '#a855f7', '#ef4444', '#ec4899', '#eab308', '#06b6d4'];

// Where the full book list is known (the map), colour by position: no two books share a colour until 8+ books.
export const bookColorAt = (index) => BOOK_COLORS[index % BOOK_COLORS.length];

export const bookColor = (name) => {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return BOOK_COLORS[h % BOOK_COLORS.length];
};

export const shortBook = (name, max = 24) => {
  const base = name.replace(/\.pdf$/i, '');
  return base.length > max ? base.slice(0, max - 2) + '...' : base;
};
