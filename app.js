/**
 * AI Autocorrect Pro — Main JavaScript
 * Modular, feature-rich frontend controller
 */

/* ============================================================
   STATE
   ============================================================ */
const state = {
  totalWords: 0,
  totalCorrections: 0,
  totalScore: 0,
  correctionCount: 0,
  totalTimeSaved: 0,
  lastCorrected: null,
  typingTimer: null,
  typingStart: null,
  wordCount: 0,
  voiceActive: false,
  recognition: null,
  loaderInterval: null,
};

/* ============================================================
   DOM REFS
   ============================================================ */
const $ = id => document.getElementById(id);

const inputText      = $('inputText');
const wordCountEl    = $('wordCount');
const charCountEl    = $('charCount');
const correctBtn     = $('correctBtn');
const outputCard     = $('outputCard');
const outputContent  = $('outputContent');
const outputPlaceholder = $('outputPlaceholder');
const loadingOverlay = $('loadingOverlay');
const correctedTextEl = $('correctedText');
const originalTextEl  = $('originalText');
const mistakesChip   = $('mistakesChip');
const scoreBadge     = $('scoreBadge');
const scoreVal       = $('scoreVal');
const changesList    = $('changesList');
const wpmDisplay     = $('wpmDisplay');
const readTimeEl     = $('readTime');
const historyList    = $('historyList');
const clearHistoryBtn = $('clearHistoryBtn');
const shortcutsModal = $('shortcutsModal');
const themeToggle    = $('themeToggle');
const dragHint       = $('dragHint');
const navbar         = $('navbar');

/* ============================================================
   THEME
   ============================================================ */
const ThemeManager = {
  init() {
    const saved = localStorage.getItem('acpro-theme') || 'light';
    this.apply(saved);
  },
  toggle() {
    const current = document.documentElement.dataset.theme;
    const next = current === 'dark' ? 'light' : 'dark';
    this.apply(next);
    localStorage.setItem('acpro-theme', next);
  },
  apply(theme) {
    document.documentElement.dataset.theme = theme;
    const icon = theme === 'dark' ? '☀️' : '🌙';
    themeToggle.querySelector('.theme-icon').textContent = icon;
  }
};

themeToggle.addEventListener('click', () => ThemeManager.toggle());
ThemeManager.init();

/* ============================================================
   NAVBAR SCROLL EFFECT
   ============================================================ */
window.addEventListener('scroll', () => {
  navbar.classList.toggle('scrolled', window.scrollY > 30);
});

/* ============================================================
   TEXT STATS
   ============================================================ */
function updateStats() {
  const text = inputText.value;
  const chars = text.length;
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const readSec = Math.ceil(words / 4);  // ~240 wpm → 4 words/sec

  charCountEl.textContent = `${chars} / 5000`;
  wordCountEl.textContent = `${words} word${words !== 1 ? 's' : ''}`;
  readTimeEl.textContent = readSec >= 60 ? `${Math.ceil(readSec/60)}m` : `${readSec}s`;

  // Char count warning
  charCountEl.style.color = chars > 4500 ? '#e74c3c' :
                            chars > 4000 ? '#f39c12' : '';

  // Typing speed
  if (!state.typingStart && text.length > 0) {
    state.typingStart = Date.now();
  }
  if (text.length === 0) {
    state.typingStart = null;
    wpmDisplay.textContent = 0;
  }

  if (state.typingTimer) clearTimeout(state.typingTimer);
  state.typingTimer = setTimeout(() => {
    if (state.typingStart && words > 0) {
      const elapsed = (Date.now() - state.typingStart) / 1000 / 60;
      const wpm = Math.round(words / elapsed);
      wpmDisplay.textContent = Math.min(wpm, 200);
    }
  }, 500);

  state.wordCount = words;
}

inputText.addEventListener('input', updateStats);

/* ============================================================
   RIPPLE EFFECT
   ============================================================ */
document.querySelectorAll('.ripple').forEach(btn => {
  btn.addEventListener('click', e => {
    const r = document.createElement('span');
    r.className = 'ripple-effect';
    const rect = btn.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    r.style.cssText = `width:${size}px;height:${size}px;
      left:${e.clientX-rect.left-size/2}px;
      top:${e.clientY-rect.top-size/2}px`;
    btn.appendChild(r);
    setTimeout(() => r.remove(), 600);
  });
});

/* ============================================================
   TOOLBAR BUTTONS
   ============================================================ */

// Paste
$('pasteBtn').addEventListener('click', async () => {
  try {
    const text = await navigator.clipboard.readText();
    inputText.value = text;
    updateStats();
    showToast('📋 Text pasted!', 'success');
  } catch {
    showToast('Paste not available — use Ctrl+V', 'error');
  }
});

// Clear
$('clearBtn').addEventListener('click', () => {
  inputText.value = '';
  updateStats();
  resetOutput();
  showToast('🗑️ Cleared!');
});

function resetOutput() {
  outputContent.style.display = 'none';
  outputPlaceholder.style.display = 'flex';
}

/* ============================================================
   VOICE INPUT
   ============================================================ */
const VoiceInput = {
  init() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      $('voiceBtn').title = 'Voice not supported in this browser';
      return;
    }
    state.recognition = new SpeechRecognition();
    state.recognition.continuous = false;
    state.recognition.interimResults = true;
    state.recognition.lang = 'en-US';

    state.recognition.onresult = e => {
      const transcript = Array.from(e.results)
        .map(r => r[0].transcript).join('');
      inputText.value = transcript;
      updateStats();
    };

    state.recognition.onend = () => {
      state.voiceActive = false;
      $('voiceBtn').innerHTML = '🎙️ Voice';
      $('voiceBtn').classList.remove('active');
    };

    state.recognition.onerror = () => {
      showToast('Voice error. Please try again.', 'error');
      state.voiceActive = false;
    };
  },

  toggle() {
    if (!state.recognition) {
      showToast('Voice input not supported', 'error');
      return;
    }
    if (state.voiceActive) {
      state.recognition.stop();
    } else {
      state.recognition.start();
      state.voiceActive = true;
      $('voiceBtn').innerHTML = `<span class="voice-wave"><span></span><span></span><span></span><span></span><span></span></span> Listening`;
      $('voiceBtn').classList.add('active');
      showToast('🎙️ Listening... Speak now!', 'success');
    }
  }
};

VoiceInput.init();
$('voiceBtn').addEventListener('click', () => VoiceInput.toggle());

/* ============================================================
   DRAG & DROP
   ============================================================ */
const DragDrop = {
  init() {
    const area = inputText.parentElement;

    area.addEventListener('dragover', e => {
      e.preventDefault();
      dragHint.classList.add('visible');
    });
    area.addEventListener('dragleave', () => {
      dragHint.classList.remove('visible');
    });
    area.addEventListener('drop', e => {
      e.preventDefault();
      dragHint.classList.remove('visible');
      const file = e.dataTransfer.files[0];
      if (file && (file.type === 'text/plain' || file.name.endsWith('.txt'))) {
        const reader = new FileReader();
        reader.onload = ev => {
          inputText.value = ev.target.result.slice(0, 5000);
          updateStats();
          showToast('📂 File loaded!', 'success');
        };
        reader.readAsText(file);
      } else {
        showToast('Only .txt files supported', 'error');
      }
    });
  }
};

DragDrop.init();

/* ============================================================
   LOADER ANIMATION
   ============================================================ */
const steps = ['ls1', 'ls2', 'ls3', 'ls4'];
const msgs  = ['Analyzing text...', 'Checking grammar...', 'Improving clarity...', 'Finalizing...'];

function startLoader() {
  loadingOverlay.classList.add('active');
  steps.forEach(id => {
    const el = $(id);
    el.classList.remove('active', 'done');
  });
  let i = 0;
  $(steps[0]).classList.add('active');
  $('loaderText').textContent = msgs[0];

  state.loaderInterval = setInterval(() => {
    $(steps[i]).classList.remove('active');
    $(steps[i]).classList.add('done');
    i++;
    if (i < steps.length) {
      $(steps[i]).classList.add('active');
      $('loaderText').textContent = msgs[i];
    }
    if (i >= steps.length - 1) clearInterval(state.loaderInterval);
  }, 600);
}

function stopLoader() {
  clearInterval(state.loaderInterval);
  loadingOverlay.classList.remove('active');
  steps.forEach(id => $(id).classList.remove('active', 'done'));
}

/* ============================================================
   MAIN CORRECTION
   ============================================================ */
async function correctText() {
  const text = inputText.value.trim();
  if (!text) { showToast('Please enter some text first!', 'error'); return; }
  if (text.length > 5000) { showToast('Text too long (max 5000 chars)', 'error'); return; }

  startLoader();
  outputPlaceholder.style.display = 'none';
  outputContent.style.display = 'none';

  const t0 = Date.now();

  try {
    const res = await fetch('/correct', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);

    stopLoader();
    renderResult(data, elapsed);
    updateDashboard(data, elapsed);
    saveHistory(data);

  } catch (err) {
    stopLoader();
    showToast('Connection error. Is the Flask server running?', 'error');
    console.error(err);
    // Show placeholder again
    outputPlaceholder.style.display = 'flex';
  }
}

correctBtn.addEventListener('click', correctText);

/* ============================================================
   RENDER RESULT
   ============================================================ */
function renderResult(data, elapsed) {
  const { original, corrected, mistakes, score, changes } = data;

  // Score
  scoreVal.textContent = score;
  const scoreEl = scoreBadge;
  scoreEl.style.background = score >= 90 ? 'linear-gradient(135deg,#2ECC71,#16A085)' :
                             score >= 70 ? 'linear-gradient(135deg,#f39c12,#e67e22)' :
                                           'linear-gradient(135deg,#e74c3c,#c0392b)';

  // Chips
  mistakesChip.textContent = `${mistakes} correction${mistakes !== 1 ? 's' : ''}`;

  // Highlight diff
  correctedTextEl.innerHTML = highlightChanges(original, corrected);
  originalTextEl.textContent = original;

  // Changes list
  changesList.innerHTML = '';
  if (changes && changes.length) {
    changes.forEach(c => {
      const tag = document.createElement('span');
      tag.className = 'change-tag';
      tag.textContent = c;
      changesList.appendChild(tag);
    });
  }

  // Store for downloads
  state.lastCorrected = { original, corrected, mistakes, score };

  outputContent.style.display = 'block';
  outputContent.style.animation = 'none';
  requestAnimationFrame(() => {
    outputContent.style.animation = '';
  });
}

/* ============================================================
   DIFF HIGHLIGHTER
   ============================================================ */
function highlightChanges(original, corrected) {
  if (original === corrected) return escapeHtml(corrected);

  // Word-level diff
  const origWords = original.split(/(\s+)/);
  const corrWords = corrected.split(/(\s+)/);

  // Simple LCS-based highlighting
  const result = [];
  let oi = 0, ci = 0;

  while (ci < corrWords.length) {
    const w = corrWords[ci];
    if (origWords[oi] === w) {
      result.push(escapeHtml(w));
      oi++; ci++;
    } else {
      // Find next match
      let found = -1;
      for (let j = oi + 1; j < Math.min(oi + 6, origWords.length); j++) {
        if (origWords[j] === w) { found = j; break; }
      }
      if (found > -1) {
        // Skip deleted words
        while (oi < found) {
          if (origWords[oi].trim()) {
            result.push(`<span class="highlight-del">${escapeHtml(origWords[oi])}</span>`);
          }
          oi++;
        }
        result.push(escapeHtml(w));
        oi++; ci++;
      } else {
        // New/changed word
        if (w.trim()) {
          result.push(`<span class="highlight-add">${escapeHtml(w)}</span>`);
        } else {
          result.push(escapeHtml(w));
        }
        ci++;
      }
    }
  }
  return result.join('');
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/* ============================================================
   DASHBOARD
   ============================================================ */
function updateDashboard(data, elapsed) {
  const words = data.original.trim().split(/\s+/).length;
  state.totalWords += words;
  state.totalCorrections += data.mistakes;
  state.totalScore = Math.round(
    (state.totalScore * state.correctionCount + data.score) / (state.correctionCount + 1)
  );
  state.correctionCount++;
  state.totalTimeSaved += parseFloat(elapsed);

  animateNum($('statWords'), state.totalWords);
  animateNum($('statCorrections'), state.totalCorrections);
  $('statAccuracy').textContent = state.totalScore + '%';
  $('statTime').textContent = state.totalTimeSaved.toFixed(1) + 's';

  // Fill bars
  const maxWords = Math.max(state.totalWords, 100);
  $('fillWords').style.width = Math.min(100, state.totalWords / maxWords * 100) + '%';
  $('fillCorrections').style.width = Math.min(100, state.totalCorrections / 50 * 100) + '%';
  $('fillAccuracy').style.width = state.totalScore + '%';
  $('fillTime').style.width = Math.min(100, state.totalTimeSaved / 60 * 100) + '%';
}

function animateNum(el, target) {
  const start = parseInt(el.textContent) || 0;
  const diff = target - start;
  const steps = 20;
  let i = 0;
  const timer = setInterval(() => {
    i++;
    el.textContent = Math.round(start + diff * (i / steps));
    if (i >= steps) clearInterval(timer);
  }, 30);
}

/* ============================================================
   COPY
   ============================================================ */
$('copyBtn').addEventListener('click', () => {
  if (!state.lastCorrected) return;
  navigator.clipboard.writeText(state.lastCorrected.corrected)
    .then(() => showToast('📋 Copied to clipboard!', 'success'))
    .catch(() => {
      // Fallback
      const ta = document.createElement('textarea');
      ta.value = state.lastCorrected.corrected;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
      showToast('📋 Copied!', 'success');
    });
});

/* ============================================================
   TEXT TO SPEECH
   ============================================================ */
$('ttsBtn').addEventListener('click', () => {
  if (!state.lastCorrected) return;
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    const utt = new SpeechSynthesisUtterance(state.lastCorrected.corrected);
    utt.rate = 0.9;
    utt.lang = 'en-US';
    window.speechSynthesis.speak(utt);
    showToast('🔊 Reading aloud...', 'success');
  } else {
    showToast('Text-to-speech not supported', 'error');
  }
});

/* ============================================================
   DOWNLOAD TXT
   ============================================================ */
$('downloadTxtBtn').addEventListener('click', () => {
  if (!state.lastCorrected) return;
  const { original, corrected, mistakes, score } = state.lastCorrected;
  const content = `AI Autocorrect Pro — Correction Report
===================================
Date: ${new Date().toLocaleString()}
Grammar Score: ${score}/100
Corrections: ${mistakes}

CORRECTED TEXT:
${corrected}

ORIGINAL TEXT:
${original}
`;
  const blob = new Blob([content], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'corrected_text.txt';
  a.click();
  showToast('📄 Downloaded!', 'success');
});

/* ============================================================
   DOWNLOAD PDF
   ============================================================ */
$('downloadPdfBtn').addEventListener('click', () => {
  if (!state.lastCorrected) return;
  if (typeof window.jspdf === 'undefined' && typeof jsPDF === 'undefined') {
    showToast('PDF library loading...', 'error');
    return;
  }

  const { jsPDF: JSPDF } = window.jspdf || { jsPDF };
  const doc = new JSPDF();

  const { original, corrected, mistakes, score } = state.lastCorrected;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(18);
  doc.setTextColor(39, 174, 96);
  doc.text('AI Autocorrect Pro', 20, 20);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10);
  doc.setTextColor(100, 100, 100);
  doc.text(`Date: ${new Date().toLocaleString()}`, 20, 30);
  doc.text(`Grammar Score: ${score}/100  |  Corrections: ${mistakes}`, 20, 37);

  doc.setDrawColor(46, 204, 113);
  doc.line(20, 42, 190, 42);

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(12);
  doc.setTextColor(0, 0, 0);
  doc.text('Corrected Text:', 20, 52);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(11);
  const cLines = doc.splitTextToSize(corrected, 170);
  doc.text(cLines, 20, 62);

  const yAfterC = 62 + cLines.length * 7;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(12);
  doc.setTextColor(150, 150, 150);
  doc.text('Original Text:', 20, yAfterC + 10);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(11);
  const oLines = doc.splitTextToSize(original, 170);
  doc.text(oLines, 20, yAfterC + 20);

  doc.save('corrected_text.pdf');
  showToast('📑 PDF Downloaded!', 'success');
});

/* ============================================================
   HISTORY (Local Storage)
   ============================================================ */
const HISTORY_KEY = 'acpro-history';
const MAX_HISTORY = 10;

function saveHistory(data) {
  let history = getHistory();
  const entry = {
    id: Date.now(),
    preview: data.original.slice(0, 80) + (data.original.length > 80 ? '...' : ''),
    original: data.original,
    corrected: data.corrected,
    score: data.score,
    mistakes: data.mistakes,
    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  };
  history.unshift(entry);
  if (history.length > MAX_HISTORY) history = history.slice(0, MAX_HISTORY);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  renderHistory();
}

function getHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; }
  catch { return []; }
}

function renderHistory() {
  const history = getHistory();
  if (!history.length) {
    historyList.innerHTML = '<div class="history-empty">No corrections yet. Start typing above!</div>';
    clearHistoryBtn.style.display = 'none';
    return;
  }

  clearHistoryBtn.style.display = 'block';
  historyList.innerHTML = history.map(item => `
    <div class="history-item">
      <div class="history-preview">${escapeHtml(item.preview)}</div>
      <div class="history-score">⭐ ${item.score}/100</div>
      <div class="history-time">${item.time}</div>
      <button class="history-reload" onclick="loadHistory(${item.id})">Load</button>
    </div>
  `).join('');
}

window.loadHistory = function(id) {
  const item = getHistory().find(h => h.id === id);
  if (!item) return;
  inputText.value = item.original;
  updateStats();
  renderResult(item, '—');
  $('tool').scrollIntoView({ behavior: 'smooth' });
  showToast('📂 History loaded!', 'success');
};

clearHistoryBtn.addEventListener('click', () => {
  localStorage.removeItem(HISTORY_KEY);
  renderHistory();
  showToast('History cleared!');
});

renderHistory();

/* ============================================================
   KEYBOARD SHORTCUTS
   ============================================================ */
document.addEventListener('keydown', e => {
  const ctrl = e.ctrlKey || e.metaKey;

  if (ctrl && e.key === 'Enter') { e.preventDefault(); correctText(); }
  if (ctrl && e.key === 'k')     { e.preventDefault(); toggleModal(); }
  if (ctrl && e.key === 'Delete'){ e.preventDefault(); $('clearBtn').click(); }
  if (ctrl && e.key === 'd')     { e.preventDefault(); ThemeManager.toggle(); }
  if (ctrl && e.key === 'm')     { e.preventDefault(); VoiceInput.toggle(); }
  if (ctrl && e.key === 'c' && state.lastCorrected && document.activeElement !== inputText) {
    // Only intercept if not in textarea
    $('copyBtn').click();
  }
  if (e.key === 'Escape') { closeModal(); }
});

/* ============================================================
   SHORTCUTS MODAL
   ============================================================ */
function toggleModal() {
  shortcutsModal.classList.toggle('active');
}
function closeModal() {
  shortcutsModal.classList.remove('active');
}

$('closeModal').addEventListener('click', closeModal);
shortcutsModal.addEventListener('click', e => {
  if (e.target === shortcutsModal) closeModal();
});

/* ============================================================
   FADE-IN OBSERVER
   ============================================================ */
const observer = new IntersectionObserver(entries => {
  entries.forEach((entry, i) => {
    if (entry.isIntersecting) {
      setTimeout(() => entry.target.classList.add('visible'), i * 80);
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.1 });

document.querySelectorAll('.fade-in').forEach(el => observer.observe(el));

/* ============================================================
   TOAST
   ============================================================ */
let toastTimer;
function showToast(msg, type = '') {
  let toast = document.querySelector('.toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.className = 'toast';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.className = `toast ${type}`;
  clearTimeout(toastTimer);
  requestAnimationFrame(() => toast.classList.add('show'));
  toastTimer = setTimeout(() => toast.classList.remove('show'), 3000);
}

/* ============================================================
   INIT RIPPLES for dynamically added buttons
   ============================================================ */
function addRipple(el) {
  el.addEventListener('click', e => {
    const r = document.createElement('span');
    r.className = 'ripple-effect';
    const rect = el.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    r.style.cssText = `width:${size}px;height:${size}px;
      left:${e.clientX-rect.left-size/2}px;
      top:${e.clientY-rect.top-size/2}px`;
    el.appendChild(r);
    setTimeout(() => r.remove(), 600);
  });
}

/* ============================================================
   INITIAL LOAD ANIMATION
   ============================================================ */
window.addEventListener('load', () => {
  // Show shortcut hint then fade it
  setTimeout(() => {
    const hint = $('shortcutHint');
    if (hint) {
      setTimeout(() => hint.style.opacity = '0', 5000);
      setTimeout(() => hint.style.display = 'none', 5500);
    }
  }, 2000);
});

/* ============================================================
   LOG
   ============================================================ */
console.log(`%c✦ AI Autocorrect Pro %c| Hackathon 2026`,
  'color:#2ECC71;font-size:16px;font-weight:bold',
  'color:#27AE60;font-size:12px');
