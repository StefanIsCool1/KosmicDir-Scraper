// Terminal output is monochrome. Hierarchy comes from brightness and weight,
// not hue: results and errors are bold/black, actions are graphite, system
// chatter recedes to #999. Shared by the Playground terminal and the Agent's
// embedded terminal so the two read as one instrument.
const CAT_STYLES = {
  INPUT: { color: '#000000', fontWeight: 600 },
  CAPTURE: { color: '#000000' },
  CLEAN: { color: '#000000' },
  ERROR: { color: '#000000', fontWeight: 600 },
  BROWSER: { color: '#555555' },
  NAV: { color: '#555555' },
  SEARCH: { color: '#555555' },
  SCROLL: { color: '#555555' },
  PARSE: { color: '#555555' },
  DETAIL: { color: '#555555' },
  PAGE: { color: '#555555' },
  LOG: { color: '#999999' },
  SYSTEM: { color: '#999999' },
}

const DEFAULT_STYLE = { color: '#555555' }

export function lineStyle(category) {
  return CAT_STYLES[category] || DEFAULT_STYLE
}
