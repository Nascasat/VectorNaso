(() => {
  const $ = (id) => document.getElementById(id);
  const modal = $('editorModal');
  const canvas = $('editorCanvas');
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const toolButtons = [...document.querySelectorAll('.vn-tool[data-tool]')];
  let tool = 'eyedropper';
  let lastTool = 'pencil';
  let color = '#11100f';
  let brush = 8;
  let tolerance = 28;
  let drawing = false;
  let lastPoint = null;
  let strokeStart = null;
  let undoStack = [];
  let originalData = null;
  let currentName = 'immagine';
  let applyCallback = null;
  const stage = document.getElementById('editorStage');
  let editorZoom = 1, panX = 0, panY = 0, spaceDown = false, panMode = false, panDrag = null;

  function setStatus(message) { $('editorStatus').textContent = message; }
  function updateBrushPreview() {
    const size = Math.max(4, Math.min(24, brush));
    const preview = $('editorBrushPreview');
    preview.style.width = `${size}px`; preview.style.height = `${size}px`; preview.style.background = color;
    const cursor = $('editorBrushCursor');
    if (canvas.width) {
      const scale = canvas.getBoundingClientRect().width / canvas.width;
      cursor.style.width = `${Math.max(2, brush * scale)}px`;
      cursor.style.height = `${Math.max(2, brush * scale)}px`;
      cursor.style.borderColor = color;
    }
  }
  function point(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(canvas.width - 1, Math.floor((event.clientX - rect.left) * canvas.width / rect.width))),
      y: Math.max(0, Math.min(canvas.height - 1, Math.floor((event.clientY - rect.top) * canvas.height / rect.height)))
    };
  }
  function updateUndoButton() {
    const button = $('editorUndo');
    button.disabled = undoStack.length === 0;
    button.title = `Annulla una delle ultime 10 modifiche (${undoStack.length} disponibili)`;
  }
  function snapshot() {
    undoStack.push(ctx.getImageData(0, 0, canvas.width, canvas.height));
    if (undoStack.length > 10) undoStack.shift();
    updateUndoButton();
  }
  function undo() {
    const state = undoStack.pop();
    if (!state) { setStatus('Non ci sono altre modifiche da annullare.'); return; }
    ctx.putImageData(state, 0, 0);
    updateUndoButton();
    setStatus(`Modifica annullata · ${undoStack.length} passaggi disponibili.`);
  }
  function setTool(next) {
    if (next !== 'eyedropper') lastTool = next;
    tool = next;
    toolButtons.forEach(button => button.classList.toggle('active', button.dataset.tool === next));
    const messages = {
      eyedropper: 'Clicca sull’immagine per prelevare un colore.',
      bucket: 'Clicca un’area contigua per riempirla col colore attivo.',
      pencil: 'Trascina per disegnare con il colore e la dimensione attivi.',
      spray: 'Trascina per spruzzare punti; lo spessore regola l’area coperta.',
      line: 'Trascina per tracciare una linea retta.',
      curve: 'Trascina per tracciare una curva morbida.',
      eraser: 'Trascina per cancellare e rendere trasparente.',
      zap: 'Clicca un’area per uniformarla al colore attivo.',
      magic: 'Clicca sullo sfondo o su un’area da rimuovere o imbiancare.',
      text: 'Clicca sull’immagine per inserire il testo impostato.'
    };
    setStatus(messages[next]);
    canvas.style.cursor = panMode ? 'grab' : (next === 'text' ? 'text' : ['bucket', 'eyedropper', 'magic', 'zap'].includes(next) ? 'pointer' : 'default');
    $('editorBrushCursor').style.display = ['pencil', 'eraser', 'spray', 'line', 'curve'].includes(next) ? 'block' : 'none';
  }
  function distanceAt(data, offset, target) {
    if (data[offset + 3] < 12) return target[3] < 12;
    if (target[3] < 12) return false;
    const dr = data[offset] - target[0], dg = data[offset + 1] - target[1], db = data[offset + 2] - target[2];
    return dr * dr + dg * dg + db * db <= tolerance * tolerance * 3;
  }
  function flood(pointAt, mode) {
    const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = image.data, width = canvas.width, height = canvas.height, count = width * height;
    if (count > 12_000_000) { setStatus('Immagine troppo grande per la selezione contigua; riducine le dimensioni prima.'); return; }
    const seed = (pointAt.y * width + pointAt.x) * 4;
    const target = [data[seed], data[seed + 1], data[seed + 2], data[seed + 3]];
    const colorBytes = color.match(/[0-9a-f]{2}/gi).map(value => parseInt(value, 16));
    if (mode === 'fill' && target[0] === colorBytes[0] && target[1] === colorBytes[1] && target[2] === colorBytes[2] && target[3] === 255) return;
    const seen = new Uint8Array(count), queue = new Int32Array(count);
    let head = 0, tail = 0;
    const seedIndex = pointAt.y * width + pointAt.x;
    seen[seedIndex] = 1; queue[tail++] = seedIndex;
    while (head < tail) {
      const index = queue[head++], offset = index * 4;
      if (mode === 'magic-transparent') data[offset + 3] = 0;
      else if (mode === 'magic-white') { data[offset] = data[offset + 1] = data[offset + 2] = 255; data[offset + 3] = 255; }
      else { data[offset] = colorBytes[0]; data[offset + 1] = colorBytes[1]; data[offset + 2] = colorBytes[2]; data[offset + 3] = 255; }
      const x = index % width, y = (index / width) | 0;
      const add = next => {
        if (seen[next]) return;
        seen[next] = 1;
        if (distanceAt(data, next * 4, target)) queue[tail++] = next;
      };
      if (x) add(index - 1); if (x + 1 < width) add(index + 1);
      if (y) add(index - width); if (y + 1 < height) add(index + width);
    }
    ctx.putImageData(image, 0, 0);
    setStatus(`${tail.toLocaleString('it-IT')} pixel modificati nell’area selezionata.`);
  }
  function drawStart(event, p) {
    drawing = true; lastPoint = p; strokeStart = p; canvas.setPointerCapture(event.pointerId);
    ctx.save(); ctx.globalCompositeOperation = tool === 'eraser' ? 'destination-out' : 'source-over';
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = brush; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    if (tool === 'pencil' || tool === 'eraser') {
      ctx.beginPath(); ctx.arc(p.x, p.y, brush / 2, 0, Math.PI * 2); ctx.fill();
    } else if (tool === 'spray') sprayAt(p);
  }
  function sprayAt(p) {
    const radius = brush * 1.5;
    const count = Math.max(3, Math.round(brush * 0.9));
    for (let i = 0; i < count; i++) {
      const angle = Math.random() * Math.PI * 2;
      const distance = Math.sqrt(Math.random()) * radius;
      const size = Math.max(0.7, Math.random() * Math.max(1.2, brush * 0.12));
      ctx.beginPath(); ctx.arc(p.x + Math.cos(angle) * distance, p.y + Math.sin(angle) * distance, size / 2, 0, Math.PI * 2); ctx.fill();
    }
  }
  canvas.addEventListener('pointerdown', event => {
    if (!canvas.width || !canvas.height) return;
    event.preventDefault(); const p = point(event);
    if (tool === 'eyedropper') {
      const px = ctx.getImageData(p.x, p.y, 1, 1).data;
      if (px[3] < 12) { setStatus('Il punto selezionato è trasparente.'); return; }
      color = '#' + [px[0], px[1], px[2]].map(v => v.toString(16).padStart(2, '0')).join('');
      $('editorColor').value = color;
      const returnTool = lastTool;
      setTool(returnTool);
      setStatus(`Colore ${color.toUpperCase()} prelevato · ${returnTool === 'bucket' ? 'secchiello' : returnTool === 'pencil' ? 'matita' : returnTool}.`);
      return;
    }
    snapshot();
    if (tool === 'bucket') { flood(p, 'fill'); return; }
    if (tool === 'zap') { flood(p, 'zap'); return; }
    if (tool === 'magic') { flood(p, $('editorMagicMode').value === 'white' ? 'magic-white' : 'magic-transparent'); return; }
    if (tool === 'text') {
      const text = $('editorText').value.trim(); if (!text) { undoStack.pop(); updateUndoButton(); setStatus('Scrivi il testo da inserire nel campo laterale.'); return; }
      ctx.save(); ctx.fillStyle = color; ctx.font = `600 ${Math.max(6, Math.min(300, +$('editorFontSize').value || 36))}px Segoe UI, Arial, sans-serif`; ctx.textBaseline = 'top'; ctx.fillText(text, p.x, p.y); ctx.restore(); setStatus('Testo inserito.'); return;
    }
    drawStart(event, p);
  });
  canvas.addEventListener('pointermove', event => {
    if (!drawing || !lastPoint) return;
    const samples = event.getCoalescedEvents ? event.getCoalescedEvents() : [event];
    for (const sample of samples) {
      const p = point(sample);
      if (p.x === lastPoint.x && p.y === lastPoint.y) continue;
      if (tool === 'line' || tool === 'curve') { lastPoint = p; continue; }
      if (tool === 'spray') {
        const dx = p.x - lastPoint.x, dy = p.y - lastPoint.y;
        const distance = Math.hypot(dx, dy), spacing = Math.max(1, brush * 0.25);
        const steps = Math.min(100, Math.ceil(distance / spacing));
        for (let i = 1; i <= steps; i++) sprayAt({ x: lastPoint.x + dx * i / steps, y: lastPoint.y + dy * i / steps });
        lastPoint = p; continue;
      }
      ctx.beginPath();
      ctx.moveTo(lastPoint.x, lastPoint.y);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      lastPoint = p;
    }
  });
  stage.addEventListener('pointermove', event => {
    const cursor = $('editorBrushCursor');
    if (cursor.style.display === 'none' || panMode) return;
    const rect = stage.getBoundingClientRect();
    cursor.style.left = `${event.clientX - rect.left}px`;
    cursor.style.top = `${event.clientY - rect.top}px`;
    updateBrushPreview();
  });
  stage.addEventListener('pointerleave', () => { $('editorBrushCursor').style.display = 'none'; });
  stage.addEventListener('pointerenter', () => { if (['pencil', 'eraser', 'spray', 'line', 'curve'].includes(tool) && !panMode) $('editorBrushCursor').style.display = 'block'; });
  function stopDraw() {
    if (!drawing) return;
    if (lastPoint && strokeStart && tool === 'line') {
      ctx.beginPath(); ctx.moveTo(strokeStart.x, strokeStart.y); ctx.lineTo(lastPoint.x, lastPoint.y); ctx.stroke();
    } else if (lastPoint && strokeStart && tool === 'curve') {
      const dx = lastPoint.x - strokeStart.x, dy = lastPoint.y - strokeStart.y;
      const length = Math.hypot(dx, dy), bend = length * 0.35;
      const control = { x: (strokeStart.x + lastPoint.x) / 2 - (dy / (length || 1)) * bend, y: (strokeStart.y + lastPoint.y) / 2 + (dx / (length || 1)) * bend };
      ctx.beginPath(); ctx.moveTo(strokeStart.x, strokeStart.y); ctx.quadraticCurveTo(control.x, control.y, lastPoint.x, lastPoint.y); ctx.stroke();
    }
    drawing = false; lastPoint = null; ctx.restore();
    strokeStart = null;
    setStatus(tool === 'eraser' ? 'Area cancellata.' : tool === 'spray' ? 'Spruzzo aggiunto.' : 'Tratto aggiunto.');
  }
  canvas.addEventListener('pointerup', stopDraw); canvas.addEventListener('pointercancel', stopDraw); canvas.addEventListener('lostpointercapture', stopDraw);
  function applyEditorView() {
    canvas.style.transform = `translate(${panX / editorZoom}px, ${panY / editorZoom}px) scale(${editorZoom})`;
    $('editorZoomLabel').textContent = `${Math.round(editorZoom * 100)}%`;
  }
  function zoomBy(factor) { editorZoom = Math.max(0.25, Math.min(8, editorZoom * factor)); applyEditorView(); }
  $('editorZoomIn').addEventListener('click', () => zoomBy(1.25));
  $('editorZoomOut').addEventListener('click', () => zoomBy(1 / 1.25));
  $('editorZoomFit').addEventListener('click', () => { editorZoom = 1; panX = panY = 0; applyEditorView(); });
  document.getElementById('editorPanToggle').addEventListener('click', event => {
    panMode = !panMode;
    event.currentTarget.setAttribute('aria-pressed', String(panMode));
    stage.style.cursor = panMode ? 'grab' : '';
    canvas.style.cursor = panMode ? 'grab' : (tool === 'text' ? 'text' : ['bucket', 'eyedropper', 'magic', 'zap'].includes(tool) ? 'pointer' : 'default');
  });
  stage.addEventListener('wheel', event => {
    if (!canvas.width) return;
    event.preventDefault(); zoomBy(event.deltaY < 0 ? 1.15 : 1 / 1.15);
  }, { passive: false });
  stage.addEventListener('pointerdown', event => {
    if (event.target.closest('.vn-editor-zoom') || (event.button !== 1 && !(event.button === 0 && (spaceDown || panMode)))) return;
    event.preventDefault(); event.stopPropagation(); panDrag = { id: event.pointerId, x: event.clientX, y: event.clientY, px: panX, py: panY };
    stage.setPointerCapture(event.pointerId); stage.classList.add('vn-panning');
  }, true);
  stage.addEventListener('pointermove', event => {
    if (!panDrag || panDrag.id !== event.pointerId) return;
    panX = panDrag.px + event.clientX - panDrag.x; panY = panDrag.py + event.clientY - panDrag.y; applyEditorView();
  });
  function endPan(event) {
    if (!panDrag || panDrag.id !== event.pointerId) return;
    panDrag = null; stage.classList.remove('vn-panning');
    if (stage.hasPointerCapture(event.pointerId)) stage.releasePointerCapture(event.pointerId);
  }
  stage.addEventListener('pointerup', endPan); stage.addEventListener('pointercancel', endPan);
  document.addEventListener('keydown', event => { if (event.code === 'Space' && !/INPUT|SELECT|TEXTAREA/.test(event.target.tagName)) { spaceDown = true; event.preventDefault(); if (!modal.classList.contains('hidden')) { stage.style.cursor = 'grab'; canvas.style.cursor = 'grab'; } } });
  document.addEventListener('keyup', event => { if (event.code === 'Space') { spaceDown = false; stage.style.cursor = panMode ? 'grab' : ''; canvas.style.cursor = panMode ? 'grab' : (tool === 'text' ? 'text' : ['bucket', 'eyedropper', 'magic', 'zap'].includes(tool) ? 'pointer' : 'default'); } });
  window.addEventListener('blur', () => { spaceDown = false; stage.style.cursor = panMode ? 'grab' : ''; canvas.style.cursor = panMode ? 'grab' : (tool === 'text' ? 'text' : ['bucket', 'eyedropper', 'magic', 'zap'].includes(tool) ? 'pointer' : 'default'); });
  toolButtons.forEach(button => button.addEventListener('click', () => setTool(button.dataset.tool)));
  $('editorColor').addEventListener('input', event => { color = event.target.value; updateBrushPreview(); });
  $('editorBrush').addEventListener('input', event => { brush = +event.target.value; updateBrushPreview(); });
  $('editorTolerance').addEventListener('input', event => { tolerance = +event.target.value; $('editorToleranceText').textContent = tolerance; });
  $('editorUndo').addEventListener('click', undo);
  $('editorRestore').addEventListener('click', () => { if (!originalData) return; snapshot(); ctx.putImageData(originalData, 0, 0); setStatus('Ripristinata l’immagine originale.'); });
  $('editorClose').addEventListener('click', () => modal.classList.add('hidden'));
  modal.addEventListener('click', event => { if (event.target === modal) modal.classList.add('hidden'); });
  $('editorApply').addEventListener('click', async () => {
    if (!applyCallback || !canvas.width) return;
    const button = $('editorApply'); button.disabled = true;
    try {
      const blob = await new Promise((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(new Error('Impossibile esportare il PNG')), 'image/png'));
      const file = new File([blob], currentName.replace(/\.[^.]+$/, '') + '-modificata.png', { type: 'image/png' });
      applyCallback(file); modal.classList.add('hidden');
    } catch (error) { setStatus(error.message); }
    finally { button.disabled = false; }
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !modal.classList.contains('hidden')) modal.classList.add('hidden'); });

  window.VectorNasoEditor = {
    async open(file, onApply) {
      currentName = file.name || 'immagine'; applyCallback = onApply; undoStack = []; updateUndoButton(); panMode = false; document.getElementById('editorPanToggle').setAttribute('aria-pressed', 'false'); stage.style.cursor = '';
      const url = URL.createObjectURL(file);
      try {
        const image = new Image(); image.src = url; await image.decode();
        canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
        ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.drawImage(image, 0, 0);
        originalData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        updateBrushPreview();
        $('editorTitle').textContent = `Correggi immagine · ${image.naturalWidth} × ${image.naturalHeight}`;
        $('editorApply').disabled = false; editorZoom = 1; panX = panY = 0; applyEditorView(); modal.classList.remove('hidden'); setTool('eyedropper');
      } catch (error) { setStatus('Impossibile aprire l’immagine: ' + error.message); modal.classList.remove('hidden'); }
      finally { URL.revokeObjectURL(url); }
    }
  };
})();
