;(function (root) {
  const GRID_SIZE = 4
  const SAMPLE_SIZE = 64
  const TILE_SIZE = SAMPLE_SIZE / GRID_SIZE
  const PIXEL_THRESHOLD = 24
  const CHANGED_PIXEL_COUNT = 5

  function grayscale(rgba) {
    const signature = new Array(SAMPLE_SIZE * SAMPLE_SIZE)
    for (let pixel = 0; pixel < signature.length; pixel++) {
      const offset = pixel * 4
      signature[pixel] = Math.round(0.299 * rgba[offset] + 0.587 * rgba[offset + 1] + 0.114 * rgba[offset + 2])
    }
    return signature
  }

  function changedTiles(previous, current) {
    if (!current || current.length !== SAMPLE_SIZE * SAMPLE_SIZE) return []
    if (!previous || previous.length !== current.length) return Array.from({ length: GRID_SIZE * GRID_SIZE }, (_, i) => i)

    const changed = []
    for (let tile = 0; tile < GRID_SIZE * GRID_SIZE; tile++) {
      const tileX = (tile % GRID_SIZE) * TILE_SIZE
      const tileY = Math.floor(tile / GRID_SIZE) * TILE_SIZE
      let changedPixels = 0
      for (let y = tileY; y < tileY + TILE_SIZE; y++) {
        for (let x = tileX; x < tileX + TILE_SIZE; x++) {
          const offset = y * SAMPLE_SIZE + x
          if (Math.abs(current[offset] - previous[offset]) >= PIXEL_THRESHOLD && ++changedPixels >= CHANGED_PIXEL_COUNT) {
            changed.push(tile)
            y = tileY + TILE_SIZE
            break
          }
        }
      }
    }
    return changed
  }

  const api = { GRID_SIZE, SAMPLE_SIZE, grayscale, changedTiles }
  root.TileDiff = api
  if (typeof module !== 'undefined' && module.exports) module.exports = api
})(globalThis)
