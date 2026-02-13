/**
 * Fingerprint interview: модалка с пошаговыми вопросами (dropdown, radio, checkbox, slider).
 * Триггер: кнопки onboarding-btn-interview, btn-author-interview.
 */
(function() {
  var tr = window.__tr || {};
  var questions = [];
  var total = 0;
  var currentIndex = 0;
  var answers = {};

  function esc(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function openConfirmModal() {
    var el = document.getElementById('interview-confirm-modal');
    if (el) el.hidden = false;
  }

  function closeConfirmModal() {
    var el = document.getElementById('interview-confirm-modal');
    if (el) el.hidden = true;
  }

  function openInterviewModal() {
    var el = document.getElementById('interview-modal');
    if (el) el.hidden = false;
  }

  var DRAFT_KEY = 'fingerprint_interview_draft';

  function clearDraftStorage() {
    try {
      sessionStorage.removeItem(DRAFT_KEY);
    } catch (e) {}
  }

  function saveDraftToStorage() {
    saveCurrentAnswer();
    try {
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ answers: answers, currentIndex: currentIndex }));
    } catch (e) {}
  }

  function loadDraftFromStorage() {
    try {
      var raw = sessionStorage.getItem(DRAFT_KEY);
      if (raw) {
        var d = JSON.parse(raw);
        if (d && typeof d.answers === 'object') {
          for (var k in d.answers) answers[k] = d.answers[k];
          if (typeof d.currentIndex === 'number' && d.currentIndex >= 0 && d.currentIndex < total) {
            currentIndex = d.currentIndex;
          }
        }
      }
    } catch (e) {}
  }

  function closeInterviewModal() {
    clearDraftStorage();
    answers = {};
    currentIndex = 0;
    window.__interviewClosedWithoutSave = true;
    fetch('/onboarding/fingerprint', { method: 'DELETE', credentials: 'include' }).catch(function() {});
    hideHistoryBlocks();
    var el = document.getElementById('interview-modal');
    if (el) el.hidden = true;
  }

  function getCurrentValue(q) {
    var storeTo = q.store_to;
    var otherOpt = q.other_option;
    var wrap = document.getElementById('interview-question-body');
    if (!wrap) return null;
    var radios = wrap.querySelectorAll('input[type="radio"][name="' + storeTo + '"]');
    var checks = wrap.querySelectorAll('input[type="checkbox"][name="' + storeTo + '"]');
    var select = wrap.querySelector('select[name="' + storeTo + '"]');
    var slider = wrap.querySelector('input[type="range"][name="' + storeTo + '"]');
    var textarea = wrap.querySelector('textarea[name="' + storeTo + '"]');
    var otherInput = wrap.querySelector('input.fp-other-input[name="' + storeTo + '_other"]');
    if (radios.length) {
      var r = wrap.querySelector('input[type="radio"][name="' + storeTo + '"]:checked');
      if (!r) return null;
      var selVal = r.value;
      if (otherOpt && selVal === otherOpt && otherInput) {
        var t = (otherInput.value || '').trim();
        return t || selVal;
      }
      return selVal;
    }
    if (checks.length) {
      var arr = Array.prototype.slice.call(wrap.querySelectorAll('input[type="checkbox"][name="' + storeTo + '"]:checked')).map(function(c) { return c.value; });
      if (otherOpt && arr.indexOf(otherOpt) >= 0 && otherInput) {
        var txt = (otherInput.value || '').trim();
        arr = arr.filter(function(v) { return v !== otherOpt; });
        if (txt) arr.push(txt);
      }
      return arr;
    }
    if (select) {
      var selVal = select.value;
      if (otherOpt && selVal === otherOpt && otherInput) {
        var t = (otherInput.value || '').trim();
        return t || selVal;
      }
      return selVal;
    }
    if (slider) return parseInt(slider.value, 10);
    if (textarea) return (textarea.value || '').trim();
    return null;
  }

  function saveCurrentAnswer() {
    if (currentIndex < 0 || currentIndex >= total || !questions[currentIndex]) return;
    var q = questions[currentIndex];
    var val = getCurrentValue(q);
    var def = q.default;
    if (val === null || val === '' || (Array.isArray(val) && val.length === 0)) {
      if (q.optional && q.ui_type === 'text_optional') val = '';
      else if (val === null && def !== undefined) val = def;
    }
    if (val !== null && (val !== '' || !q.optional)) answers[q.store_to] = val;
    var wrap = document.getElementById('interview-question-body');
    if (wrap && q.followup_fields) {
      q.followup_fields.forEach(function(f) {
        var inp = wrap.querySelector('textarea[name="' + f.store_to + '"], input[name="' + f.store_to + '"]');
        if (inp) answers[f.store_to] = (inp.value || '').trim() || null;
      });
    }
  }

  function renderQuestionBody(q) {
    var storeTo = q.store_to;
    var saved = answers[storeTo];
    var html = '';
    if (q.ui_type === 'radio') {
      var otherOpt = q.other_option;
      var isOther = otherOpt && (saved && q.options && q.options.indexOf(saved) < 0);
      var otherVal = isOther ? saved : '';
      html = '<div class="fp-options" role="radiogroup" aria-label="' + esc(q.question) + '">';
      (q.options || []).forEach(function(opt) {
        var checked = (isOther ? opt === otherOpt : (saved !== undefined ? saved === opt : opt === q.default)) ? ' checked' : '';
        html += '<label class="fp-option"><input type="radio" name="' + esc(storeTo) + '" value="' + esc(opt) + '"' + checked + '> ' + esc(opt) + '</label>';
      });
      html += '</div>';
      if (otherOpt) {
        html += '<div class="fp-other-wrap" id="fp-other-wrap-' + esc(storeTo) + '" style="' + (isOther ? '' : 'display:none;') + ' margin-top: var(--space-3);">';
        html += '<label class="fp-other-label"><span class="fp-required">*</span> ' + (tr.onboarding_other_required || 'Обязательно укажите') + '</label>';
        html += '<input type="text" class="fp-other-input fp-textarea" name="' + esc(storeTo) + '_other" placeholder="' + esc(q.other_placeholder || 'Укажите свой вариант') + '" value="' + esc(otherVal) + '">';
        html += '</div>';
      }
    } else if (q.ui_type === 'checkbox') {
      var defArr = Array.isArray(q.default) ? q.default : [q.default];
      var savedArr = Array.isArray(saved) ? saved : (saved ? [saved] : []);
      var otherOpt = q.other_option;
      var otherVal = '';
      if (otherOpt && savedArr.length) {
        var notInOpts = savedArr.filter(function(v) { return !q.options || q.options.indexOf(v) < 0; });
        if (notInOpts.length) otherVal = notInOpts[0];
        savedArr = savedArr.filter(function(v) { return q.options && q.options.indexOf(v) >= 0; });
        if (otherVal) savedArr.push(otherOpt);
      }
      var useVal = saved !== undefined ? savedArr : defArr;
      html = '<div class="fp-options" role="group">';
      (q.options || []).forEach(function(opt) {
        var checked = useVal.indexOf(opt) >= 0 ? ' checked' : '';
        html += '<label class="fp-option"><input type="checkbox" name="' + esc(storeTo) + '" value="' + esc(opt) + '"' + checked + '> ' + esc(opt) + '</label>';
      });
      html += '</div>';
      if (otherOpt) {
        var isOtherChecked = useVal.indexOf(otherOpt) >= 0;
        html += '<div class="fp-other-wrap" id="fp-other-wrap-' + esc(storeTo) + '" style="' + (isOtherChecked ? '' : 'display:none;') + ' margin-top: var(--space-3);">';
        html += '<label class="fp-other-label"><span class="fp-required">*</span> ' + (tr.onboarding_other_required || 'Обязательно укажите') + '</label>';
        html += '<input type="text" class="fp-other-input fp-textarea" name="' + esc(storeTo) + '_other" placeholder="' + esc(q.other_placeholder || 'Укажите свой вариант') + '" value="' + esc(otherVal) + '">';
        html += '</div>';
      }
      if (q.max_select) html += '<p class="fp-hint">' + (tr.onboarding_select_up_to || 'Выбери до') + ' ' + q.max_select + '</p>';
    } else if (q.ui_type === 'dropdown') {
      var def = q.default;
      var val = saved !== undefined ? saved : def;
      var otherOpt = q.other_option;
      var isOther = otherOpt && (val === otherOpt || (val && q.options && q.options.indexOf(val) < 0));
      var otherVal = isOther && val !== otherOpt ? val : '';
      html = '<select name="' + esc(storeTo) + '" class="fp-select" id="fp-select-' + esc(storeTo) + '">';
      (q.options || []).forEach(function(opt) {
        var sel = (isOther ? opt === otherOpt : val === opt) ? ' selected' : '';
        html += '<option value="' + esc(opt) + '"' + sel + '>' + esc(opt) + '</option>';
      });
      html += '</select>';
      if (otherOpt) {
        html += '<div class="fp-other-wrap" id="fp-other-wrap-' + esc(storeTo) + '" style="' + (isOther ? '' : 'display:none;') + ' margin-top: var(--space-3);">';
        html += '<label class="fp-other-label"><span class="fp-required">*</span> ' + (tr.onboarding_other_required || 'Обязательно укажите') + '</label>';
        html += '<input type="text" class="fp-other-input fp-textarea" name="' + esc(storeTo) + '_other" placeholder="' + esc(q.other_placeholder || 'Укажите свой вариант') + '" value="' + esc(otherVal) + '">';
        html += '</div>';
      }
    } else if (q.ui_type === 'slider') {
      var min = (q.options && q.options[0]) || 1;
      var max = (q.options && q.options[1]) || 10;
      var val = saved !== undefined ? saved : (q.default !== undefined ? q.default : min);
      var labels = q.slider_labels || {};
      var minLabel = labels.min || labels[min] || '';
      var maxLabel = labels.max || labels[max] || '';
      html = '<div class="fp-slider-wrap">';
      if (minLabel) html += '<span class="fp-slider-label fp-slider-label-min"><span class="fp-slider-num">' + min + '</span> ' + esc(minLabel) + '</span>';
      html += '<input type="range" name="' + esc(storeTo) + '" class="fp-slider" min="' + min + '" max="' + max + '" value="' + val + '" aria-label="' + esc(q.question) + '"><span class="fp-slider-value" data-for="' + esc(storeTo) + '">' + val + '</span>';
      if (maxLabel) html += '<span class="fp-slider-label fp-slider-label-max"><span class="fp-slider-num">' + max + '</span> ' + esc(maxLabel) + '</span>';
      html += '</div>';
    } else if (q.ui_type === 'text_optional') {
      html = '<textarea name="' + esc(storeTo) + '" class="fp-textarea" rows="3" placeholder="' + esc(q.default || '') + '">' + esc(saved || '') + '</textarea>';
    }
    if (q.followup_fields && q.followup_fields.length) {
      q.followup_fields.forEach(function(f, idx) {
        var fSaved = answers[f.store_to];
        var showWhen = f.show_when;
        var mainVal = saved !== undefined ? saved : (q.default !== undefined ? q.default : null);
        var isVisible;
        if (!showWhen) {
          isVisible = true;
        } else if (Array.isArray(mainVal)) {
          isVisible = mainVal.some(function(v) { return showWhen.indexOf(v) >= 0; });
        } else {
          isVisible = mainVal && showWhen.indexOf(mainVal) >= 0;
        }
        html += '<div class="fp-followup fp-followup-' + esc(storeTo) + '-' + idx + '" data-store-to="' + esc(f.store_to) + '" data-show-when="' + esc(showWhen ? JSON.stringify(showWhen) : '') + '" data-optional="' + (f.optional ? '1' : '0') + '" style="margin-top: var(--space-4);' + (isVisible ? '' : ' display:none;') + '">';
        html += '<label class="fp-followup-label">' + esc(f.label || '') + (f.optional ? '' : ' <span class="fp-required">*</span>') + '</label>';
        html += '<textarea name="' + esc(f.store_to) + '" class="fp-textarea fp-followup-input" rows="2" placeholder="' + esc(f.placeholder || '') + '">' + esc(fSaved || '') + '</textarea>';
        html += '</div>';
      });
    }
    var body = document.getElementById('interview-question-body');
    if (body) body.innerHTML = html || '';

    if (q.ui_type === 'slider' && body) {
      var slider = body.querySelector('input[type="range"]');
      if (slider) {
        var min = parseInt(slider.min, 10) || 1;
        var max = parseInt(slider.max, 10) || 10;
        function updateSliderPct() {
          var val = parseInt(slider.value, 10);
          var pct = ((val - min) / (max - min) * 100) + '%';
          slider.style.setProperty('--slider-pct', pct);
        }
        updateSliderPct();
        slider.addEventListener('input', function() {
          var sv = body.querySelector('.fp-slider-value[data-for="' + storeTo + '"]');
          if (sv) sv.textContent = slider.value;
          updateSliderPct();
        });
      }
    }
    if (q.ui_type === 'checkbox' && body) {
      var checks = body.querySelectorAll('input[type="checkbox"][name="' + storeTo + '"]');
      var exclusiveOpt = q.exclusive_option;
      checks.forEach(function(cb) {
        cb.addEventListener('change', function() {
          if (exclusiveOpt) {
            if (cb.value === exclusiveOpt && cb.checked) {
              checks.forEach(function(c) { if (c !== cb) c.checked = false; });
            } else if (cb.value !== exclusiveOpt && cb.checked) {
              var excCb = body.querySelector('input[type="checkbox"][name="' + storeTo + '"][value="' + exclusiveOpt + '"]');
              if (excCb) excCb.checked = false;
            }
          }
          if (q.max_select) {
            var checked = body.querySelectorAll('input[type="checkbox"][name="' + storeTo + '"]:checked');
            if (checked.length > q.max_select) checked[q.max_select].checked = false;
          }
        });
      });
    }
    if (q.other_option && body) {
      var otherOpt = q.other_option;
      var otherWrap = body.querySelector('[id="fp-other-wrap-' + storeTo.replace(/"/g, '\\"') + '"]');
      if (q.ui_type === 'dropdown') {
        var sel = body.querySelector('select[name="' + storeTo + '"]');
        if (sel && otherWrap) {
          function toggleOther() {
            otherWrap.style.display = sel.value === otherOpt ? '' : 'none';
          }
          sel.addEventListener('change', toggleOther);
        }
      } else if (q.ui_type === 'checkbox') {
        var otherCb = body.querySelector('input[type="checkbox"][name="' + storeTo + '"][value="' + otherOpt + '"]');
        if (otherCb && otherWrap) {
          function toggleOther() {
            otherWrap.style.display = otherCb.checked ? '' : 'none';
          }
          otherCb.addEventListener('change', toggleOther);
        }
      } else if (q.ui_type === 'radio') {
        var otherRadio = body.querySelector('input[type="radio"][name="' + storeTo + '"][value="' + otherOpt + '"]');
        if (otherRadio && otherWrap) {
          function toggleOther() {
            otherWrap.style.display = otherRadio.checked ? '' : 'none';
          }
          body.querySelectorAll('input[type="radio"][name="' + storeTo + '"]').forEach(function(r) { r.addEventListener('change', toggleOther); });
        }
      }
    }
    if (q.followup_fields && body) {
      var followups = body.querySelectorAll('.fp-followup[data-show-when]');
      if (followups.length) {
        function updateFollowupVisibility() {
          var vals = [];
          if (q.ui_type === 'radio') {
            var r = body.querySelector('input[type="radio"][name="' + storeTo + '"]:checked');
            if (r) vals = [r.value];
          } else if (q.ui_type === 'checkbox') {
            vals = Array.from(body.querySelectorAll('input[type="checkbox"][name="' + storeTo + '"]:checked')).map(function(c) { return c.value; });
          }
          followups.forEach(function(fw) {
            var sw = fw.getAttribute('data-show-when');
            if (!sw) return;
            var showWhen = JSON.parse(sw);
            var visible = vals.some(function(v) { return showWhen.indexOf(v) >= 0; });
            fw.style.display = visible ? '' : 'none';
            if (!visible) {
              var ta = fw.querySelector('textarea');
              if (ta) ta.value = '';
            }
          });
        }
        if (q.ui_type === 'radio') {
          body.querySelectorAll('input[type="radio"][name="' + storeTo + '"]').forEach(function(r) { r.addEventListener('change', updateFollowupVisibility); });
        } else if (q.ui_type === 'checkbox') {
          body.querySelectorAll('input[type="checkbox"][name="' + storeTo + '"]').forEach(function(cb) { cb.addEventListener('change', updateFollowupVisibility); });
        }
      }
    }
  }

  function renderQuestion() {
    if (currentIndex < 0 || currentIndex >= total) return;
    var q = questions[currentIndex];
    var progressFill = document.getElementById('interview-progress-fill');
    var progressText = document.getElementById('interview-progress-text');
    var sectionLabel = document.getElementById('interview-section-label');
    var questionTitle = document.getElementById('interview-question-title');
    var btnPrev = document.getElementById('interview-prev');
    var btnNext = document.getElementById('interview-next');

    if (progressFill) progressFill.style.width = (total ? ((currentIndex + 1) / total) * 100 : 0) + '%';
    if (progressText) progressText.textContent = (tr.interview_question_progress_full || 'Вопрос {0} из {1} · осталось примерно {2} мин')
      .replace('{0}', currentIndex + 1).replace('{1}', total).replace('{2}', Math.max(0, Math.ceil((total - currentIndex - 1) * 0.5)));
    if (sectionLabel) {
      sectionLabel.textContent = q.section_title || '';
      sectionLabel.classList.toggle('interview-section-extra', (q.section_title || '').indexOf('Дополнительно') >= 0);
    }
    if (questionTitle) questionTitle.textContent = (typeof q.id === 'number' ? q.id + '. ' : '') + (q.question || '');

    renderQuestionBody(q);

    if (btnPrev) btnPrev.style.display = currentIndex > 0 ? 'inline-block' : 'none';
    if (btnNext) {
      btnNext.style.display = 'inline-block';
      btnNext.textContent = currentIndex === total - 1 ? (tr.interview_finish || 'Завершить') : (tr.interview_next || 'Далее');
      btnNext.classList.toggle('interview-finish-btn', currentIndex === total - 1);
    }
    var questionBox = document.querySelector('.interview-question-box');
    if (questionBox) {
      questionBox.classList.toggle('interview-last-question', currentIndex === total - 1);
      questionBox.scrollTop = 0;
    }
  }

  function applyFingerprint(fp) {
    function flatten(obj, prefix) {
      prefix = prefix || '';
      var out = {};
      for (var k in obj) {
        var v = obj[k];
        var path = prefix ? prefix + '.' + k : k;
        if (v && typeof v === 'object' && !Array.isArray(v)) {
          var flat = flatten(v, path);
          for (var key in flat) out[key] = flat[key];
        } else {
          out[path] = v;
        }
      }
      return out;
    }
    var flat = flatten(fp);
    for (var p in flat) answers[p] = flat[p];
  }

  function buildPayload() {
    var payload = {};
    questions.forEach(function(q) {
      var v = answers[q.store_to];
      if (v !== undefined && v !== null && (v !== '' || !q.optional)) payload[q.store_to] = v;
      else if (!q.optional && q.ui_type !== 'text_optional') payload[q.store_to] = q.default;
      if (q.followup_fields) {
        q.followup_fields.forEach(function(f) {
          if (f.store_to in answers) payload[f.store_to] = answers[f.store_to];
        });
      }
    });
    return payload;
  }

  function formatFingerprintForHistory(fp) {
    if (!fp || typeof fp !== 'object') return '';
    var lines = [];
    function walk(obj, prefix) {
      for (var k in obj) {
        var v = obj[k];
        var path = prefix ? prefix + '.' + k : k;
        if (v && typeof v === 'object' && !Array.isArray(v)) {
          walk(v, path);
        } else if (v !== undefined && v !== null && v !== '') {
          var val = Array.isArray(v) ? v.join(', ') : String(v);
          lines.push(path + ': ' + val);
        }
      }
    }
    walk(fp, '');
    return lines.join('\n');
  }

  function updateAuthorHistoryFromFingerprint(fp) {
    var text = formatFingerprintForHistory(fp);
    if (!text) return;
    var areas = document.querySelectorAll('textarea[name="author_history"]');
    var ta = areas.length ? areas[0] : null;
    if (!ta) {
      ta = document.getElementById('onboarding-author-history');
    }
    if (ta) {
      var existing = (ta.value || '').trim();
      ta.value = existing ? existing + '\n\n--- Fingerprint ---\n' + text : text;
      ta.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  function showHistoryBlocks() {
    window.__fingerprintCompleted = true;
    var w = document.getElementById('onboarding-history-wrap');
    if (w) w.style.display = '';
    document.querySelectorAll('.author-history-wrap').forEach(function(el) { el.style.display = ''; });
    var saveAuthors = document.getElementById('save-authors');
    if (saveAuthors) saveAuthors.style.display = '';
    var resetLink = document.getElementById('reset-fingerprint-link');
    if (resetLink) resetLink.style.display = '';
  }

  function hideHistoryBlocks() {
    window.__fingerprintCompleted = false;
    var w = document.getElementById('onboarding-history-wrap');
    if (w) w.style.display = 'none';
    document.querySelectorAll('.author-history-wrap').forEach(function(el) { el.style.display = 'none'; });
    var saveAuthors = document.getElementById('save-authors');
    if (saveAuthors) saveAuthors.style.display = 'none';
    var resetLink = document.getElementById('reset-fingerprint-link');
    if (resetLink) resetLink.style.display = 'none';
  }

  window.syncAuthorFormVisibility = function() {
    if (window.__fingerprintCompleted) {
      showHistoryBlocks();
    } else {
      hideHistoryBlocks();
    }
  };

  window.resetFingerprint = function() {
    fetch('/onboarding/fingerprint', { method: 'DELETE', credentials: 'include' })
      .then(function(r) { return r.json().catch(function() { return {}; }); })
      .then(function(data) {
        if (data && data.ok) {
          hideHistoryBlocks();
          if (typeof window.toast === 'function') window.toast('Fingerprint сброшен');
        }
      })
      .catch(function() {});
  };

  function saveFingerprintAndClose() {
    saveCurrentAnswer();
    saveDraftToStorage();
    var payload = buildPayload();
    fetch('/onboarding/fingerprint', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'include'
    }).then(function(r) {
      return r.json().catch(function() { return {}; });
    }).then(function(data) {
      if (data && data.ok) {
        if (typeof window.toast === 'function') {
          window.toast(tr.onboarding_fp_saved || 'Fingerprint сохранён');
        }
        if (data.fingerprint && Object.keys(data.fingerprint).length > 0) {
          showHistoryBlocks();
          updateAuthorHistoryFromFingerprint(data.fingerprint);
        }
      }
    }).catch(function() {});
    var el = document.getElementById('interview-modal');
    if (el) el.hidden = true;
  }

  function onPrev() {
    saveCurrentAnswer();
    if (currentIndex > 0) {
      currentIndex--;
      renderQuestion();
    }
  }

  function validateRequiredFollowups() {
    var q = questions[currentIndex];
    if (!q || !q.followup_fields) return true;
    var body = document.getElementById('interview-question-body');
    if (!body) return true;
    for (var i = 0; i < q.followup_fields.length; i++) {
      var f = q.followup_fields[i];
      if (f.optional) continue;
      var fw = body.querySelector('.fp-followup[data-store-to="' + f.store_to + '"]');
      if (!fw || fw.style.display === 'none') continue;
      var ta = fw.querySelector('textarea');
      if (ta && !(ta.value || '').trim()) return false;
    }
    return true;
  }

  function validateCurrentQuestion() {
    var q = questions[currentIndex];
    if (!q || q.optional) return true;
    var val = getCurrentValue(q);
    if (val === null) return false;
    if (val === '') return false;
    if (Array.isArray(val) && val.length === 0) return false;
    return true;
  }

  function validateRequiredOther() {
    var q = questions[currentIndex];
    if (!q || !q.other_option) return true;
    var body = document.getElementById('interview-question-body');
    if (!body) return true;
    var otherOpt = q.other_option;
    var storeTo = q.store_to;
    var isOtherSelected = false;
    if (q.ui_type === 'checkbox') {
      var otherCb = body.querySelector('input[type="checkbox"][name="' + storeTo + '"][value="' + otherOpt + '"]');
      isOtherSelected = otherCb && otherCb.checked;
    } else if (q.ui_type === 'dropdown') {
      var sel = body.querySelector('select[name="' + storeTo + '"]');
      isOtherSelected = sel && sel.value === otherOpt;
    } else if (q.ui_type === 'radio') {
      var r = body.querySelector('input[type="radio"][name="' + storeTo + '"]:checked');
      isOtherSelected = r && r.value === otherOpt;
    }
    if (!isOtherSelected) return true;
    var otherInput = body.querySelector('input.fp-other-input[name="' + storeTo + '_other"], textarea[name="' + storeTo + '_other"]');
    return otherInput && (otherInput.value || '').trim().length > 0;
  }

  function onNext() {
    saveCurrentAnswer();
    if (!validateCurrentQuestion() || !validateRequiredFollowups() || !validateRequiredOther()) {
      if (typeof window.toast === 'function') window.toast(tr.onboarding_fill_required || 'Заполните обязательные поля');
      return;
    }
    if (currentIndex < total - 1) {
      currentIndex++;
      renderQuestion();
    } else {
      saveFingerprintAndClose();
    }
  }

  function startFingerprintInterview() {
    closeConfirmModal();
    var locale = (window.__locale || 'ru').toLowerCase();
    var url = '/onboarding/questions/flat' + (locale === 'en' ? '?locale=en' : '');
    fetch(url, { credentials: 'include' })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        questions = (data && data.questions) || [];
        total = questions.length;
        currentIndex = 0;
        answers = {};
        return fetch('/onboarding/fingerprint', { credentials: 'include' });
      })
      .then(function(r) { return r.ok ? r.json() : {}; })
      .then(function(fp) {
        if (window.__interviewClosedWithoutSave) {
          window.__interviewClosedWithoutSave = false;
          fp = {};
        }
        if (fp && Object.keys(fp).length > 0) {
          function flatten(obj, prefix) {
            prefix = prefix || '';
            var out = {};
            for (var k in obj) {
              var v = obj[k];
              var path = prefix ? prefix + '.' + k : k;
              if (v && typeof v === 'object' && !Array.isArray(v)) {
                var flat = flatten(v, path);
                for (var key in flat) out[key] = flat[key];
              } else {
                out[path] = v;
              }
            }
            return out;
          }
          var flat = flatten(fp);
          for (var p in flat) answers[p] = flat[p];
        }
        loadDraftFromStorage();
        openInterviewModal();
        renderQuestion();
      })
      .catch(function() {
        questions = [];
        total = 0;
        openInterviewModal();
        renderQuestion();
      });
  }

  function attachListeners() {
    document.body.addEventListener('click', function(e) {
      var btn = e.target && (e.target.closest ? e.target.closest('#onboarding-btn-interview, #btn-author-interview') : null);
      if (btn) {
        e.preventDefault();
        e.stopPropagation();
        openConfirmModal();
      }
    });

    var el = document.getElementById('interview-confirm-no');
    if (el) el.addEventListener('click', closeConfirmModal);

    el = document.getElementById('interview-confirm-yes');
    if (el) el.addEventListener('click', startFingerprintInterview);

    el = document.getElementById('interview-prev');
    if (el) el.addEventListener('click', onPrev);

    el = document.getElementById('interview-next');
    if (el) el.addEventListener('click', onNext);

    el = document.getElementById('interview-save');
    if (el) el.addEventListener('click', saveFingerprintAndClose);

    el = document.getElementById('interview-close');
    if (el) el.addEventListener('click', closeInterviewModal);

    el = document.getElementById('interview-modal');
    if (el) el.addEventListener('click', function(ev) {
      if (ev.target === el) closeInterviewModal();
    });

    el = document.getElementById('interview-confirm-modal');
    if (el) el.addEventListener('click', function(ev) {
      if (ev.target === el) closeConfirmModal();
    });
  }

  function initHistoryVisibility() {
    hideHistoryBlocks();
    fetch('/onboarding/fingerprint', { credentials: 'include' })
      .then(function(r) { return r.ok ? r.json() : {}; })
      .then(function(fp) {
        if (fp && typeof fp === 'object' && Object.keys(fp).length > 0) {
          showHistoryBlocks();
          updateAuthorHistoryFromFingerprint(fp);
        } else {
          hideHistoryBlocks();
        }
      })
      .catch(function() { hideHistoryBlocks(); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      attachListeners();
      initHistoryVisibility();
    });
  } else {
    attachListeners();
    initHistoryVisibility();
  }
})();
