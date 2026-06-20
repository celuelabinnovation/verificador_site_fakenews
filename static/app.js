const form = document.getElementById('checkForm');
const urlInput = document.getElementById('urlInput');
const loading = document.getElementById('loading');
const errorBox = document.getElementById('error');
const result = document.getElementById('result');

function setList(id, items, renderer) {
  const el = document.getElementById(id);
  el.innerHTML = '';
  if (!items || !items.length) {
    const li = document.createElement('li');
    li.textContent = 'Nada encontrado nesta etapa.';
    el.appendChild(li);
    return;
  }
  items.forEach(item => {
    const li = document.createElement('li');
    li.innerHTML = renderer(item);
    el.appendChild(li);
  });
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>"']/g, s => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[s]));
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value || '-';
}

function pointRenderer(item) {
  return `<strong>${escapeHtml(item.claim || item.item || '')}</strong><br><span>${escapeHtml(item.reason || item.weight || '')}</span>`;
}

function linkRenderer(link) {
  return `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">${escapeHtml(link)}</a>`;
}

function render(data) {
  setText('scoreText', `${data.score}%`);
  setText('classification', data.classification);
  setText('analysisMode', data.analysis_mode || 'Heurística local');
  setText('localScore', data.local_score !== null && data.local_score !== undefined ? `${data.local_score}%` : '-');
  setText('aiScore', data.ai_score !== null && data.ai_score !== undefined ? `${data.ai_score}%` : 'IA não ativada');

  const gauge = document.getElementById('gaugeFill').parentElement;
  gauge.style.background = `conic-gradient(var(--accent) ${data.score * 3.6}deg, #e6ebf5 0deg)`;

  setText('domain', data.domain || '-');
  setText('title', data.metadata?.title || '-');
  setText('author', data.metadata?.author || 'Não identificado');
  setText('published', data.metadata?.published || 'Não identificada');

  setList('positiveList', data.positive_evidence, item => `${escapeHtml(item.item)} <strong>${escapeHtml(item.weight)}</strong>`);
  setList('riskList', data.risk_points, item => `${escapeHtml(item.item)} <strong>${escapeHtml(item.weight)}</strong>`);
  setList('claimsList', data.claims, item => escapeHtml(item.text));
  setList('linksList', data.trusted_links, linkRenderer);

  const aiBox = document.getElementById('aiBox');
  const aiWarning = document.getElementById('aiWarning');
  const ai = data.ai_analysis;

  if (ai) {
    aiBox.classList.remove('muted-card');
    setText('aiSummary', ai.summary || 'A IA não trouxe síntese textual.');
    setText('aiConfidence', `${ai.confidence || 0}%`);
    setList('realList', ai.real_points, pointRenderer);
    setList('unverifiedList', ai.unverified_points, pointRenderer);
    setList('suspiciousList', ai.false_or_suspicious_points, pointRenderer);
    setList('recommendationList', ai.recommendations, item => escapeHtml(item));
    aiWarning.textContent = '';
    aiWarning.classList.add('hidden');
  } else {
    aiBox.classList.add('muted-card');
    setText('aiSummary', 'A análise por IA não está ativa. Configure OPENAI_API_KEY no arquivo .env ou nas variáveis de ambiente.');
    setText('aiConfidence', '-');
    setList('realList', [], pointRenderer);
    setList('unverifiedList', [], pointRenderer);
    setList('suspiciousList', [], pointRenderer);
    setList('recommendationList', [], item => escapeHtml(item));
    if (data.ai_error) {
      aiWarning.textContent = data.ai_error;
      aiWarning.classList.remove('hidden');
    }
  }

  const checks = [];
  (data.claimreview_on_page || []).forEach(c => checks.push({source: c.author || 'ClaimReview na página', claim: c.claim, rating: c.rating, url: c.url}));
  (data.external_factchecks || []).forEach(c => checks.push({source: c.publisher || 'Fact-check externo', claim: c.claim, rating: c.rating, url: c.url}));
  setList('checksList', checks, c => {
    const url = c.url ? `<br><a href="${escapeHtml(c.url)}" target="_blank" rel="noopener">abrir checagem</a>` : '';
    return `<strong>${escapeHtml(c.source)}</strong>: ${escapeHtml(c.rating || 'sem avaliação textual')}<br>${escapeHtml(c.claim || '')}${url}`;
  });
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  result.classList.add('hidden');
  errorBox.classList.add('hidden');
  loading.classList.remove('hidden');

  try {
    const resp = await fetch('/api/check', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: urlInput.value})
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Erro ao analisar a página.');
    render(data);
    result.classList.remove('hidden');
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.classList.remove('hidden');
  } finally {
    loading.classList.add('hidden');
  }
});
