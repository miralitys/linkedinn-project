/**
 * Shared interview logic for author setup (onboarding + Settings page).
 * Uses window.__tr, window.__locale. Fills #onboarding-author-history or #authors-wrap textarea.
 */
(function() {
  var tr = window.__tr || {};
  var locale = (window.__locale || 'ru').toLowerCase().startsWith('en') ? 'en' : 'ru';
  var INTERVIEW_QUESTIONS_RU = [
    { s: "1) Кто я по легенде (персонаж)", q: "Где ты родился и откуда ты «по вайбу»? (город/регион, 1 строка)" },
    { s: "1) Кто я по легенде (персонаж)", q: "Когда и почему переехал(а)? (год + 1-2 причины)" },
    { s: "1) Кто я по легенде (персонаж)", q: "Были ли страны/города, которые сильно повлияли? (где жил(а), сколько, что изменило)" },
    { s: "1) Кто я по легенде (персонаж)", q: "Где живешь сейчас и как это правильно называть безопасно? (город/регион, допустимые формулировки)" },
    { s: "1) Кто я по легенде (персонаж)", q: "Главный проект/достижение, которое дает тебе право «говорить по теме»: что это было, какую проблему решал(а), чем закончилось? (коротко)" },
    { s: "1) Кто я по легенде (персонаж)", q: "Был ли акселератор/программа типа YC? Какая именно и как корректно это упоминать без понтов?" },
    { s: "1) Кто я по легенде (персонаж)", q: "В каких 3-5 темах ты реально эксперт(ка)? (списком)" },
    { s: "1) Кто я по легенде (персонаж)", q: "Чем занимаешься сейчас? (название проекта/компании, что делает, 1-2 предложения)" },
    { s: "1) Кто я по легенде (персонаж)", q: "Возраст, семейный статус, дети, быт: что из этого можно упоминать и как? (без деанона)" },
    { s: "1) Кто я по легенде (персонаж)", q: "Какие 2-4 «человеческие» детали добавляют объем? (хобби, музыка, спорт, игры)" },
    { s: "1) Кто я по легенде (персонаж)", q: "Практики/привычки типа медитации: есть? какие? как об этом говорить спокойно?" },
    { s: "1) Кто я по легенде (персонаж)", q: "Есть ли культурные штуки типа фестивалей/комьюнити (Burning Man): можно ли упоминать, и как аккуратно?" },
    { s: "1) Кто я по легенде (персонаж)", q: "Какие факты о себе ты упоминаешь только когда это реально к месту, а не в каждом посте/ответе? (списком). Примеры: «поднимал инвестиции», «был в YC», «делал большой продукт»." },
    { s: "1) Кто я по легенде (персонаж)", q: "Для 4 контекстов (логистика/индустрия, стартапы/AI, жизнь/выгорание/семья, музыка/игры/хобби): какие 1-2 «якоря опыта» ты вставляешь мимоходом?" },
    { s: "2) Общий тон: как я говорю", q: "Как ты сам описал(а) бы свой тон 3 словами?" },
    { s: "2) Общий тон: как я говорю", q: "Что для тебя «разговорно и тепло» в тексте? (2-3 правила)" },
    { s: "2) Общий тон: как я говорю", q: "Какая длина предложений у тебя естественная? (коротко/средне/иногда длинно)" },
    { s: "2) Общий тон: как я говорю", q: "Насколько ты прямой(ая) по шкале 1-10?" },
    { s: "2) Общий тон: как я говорю", q: "Как ты сохраняешь уважение, когда человек тупит/горит? (2-3 приемчика)" },
    { s: "2) Общий тон: как я говорю", q: "Юмор: какой именно юмор у тебя «сухой и спокойный»? (1-2 предложения)" },
    { s: "2) Общий тон: как я говорю", q: "Как ты обычно входишь в ответ? (2-3 типовых начала)" },
    { s: "2) Общий тон: как я говорю", q: "Дай 5 стартовых фраз, которые реально звучат как ты (можно на английском, как в примере)" },
    { s: "3) Что я никогда не делаю", q: "Какие 5 вещей ты никогда не пишешь (стиль/интонация/позиция)?" },
    { s: "3) Что я никогда не делаю", q: "Какие фразы или «запахи текста» ты ненавидишь? (пример: пафос, канцелярит)" },
    { s: "3) Что я никогда не делаю", q: "Какие темы ты не трогаешь вообще? (списком)" },
    { s: "3) Что я никогда не делаю", q: "Как ты отвечаешь, когда тебя тянут в психотерапию/диагнозы? (2-3 безопасные формулировки)" },
    { s: "3) Что я никогда не делаю", q: "Какие слова из «бизнес-английского» ты точно не используешь? (списком)" },
    { s: "3) Что я никогда не делаю", q: "В каких случаях ты все же упоминаешь статус/опыт, и как это звучит «без флекса»? (2-3 примера)" },
    { s: "3) Что я никогда не делаю", q: "Какие «общие ответы» ты запрещаешь себе? (типа It depends) И чем их заменяешь?" },
    { s: "4) Структура типичного ответа", q: "Сколько абзацев обычно? (диапазон)" },
    { s: "4) Структура типичного ответа", q: "Твой стандартный порядок: что идет первым, вторым, третьим? (схема)" },
    { s: "4) Структура типичного ответа", q: "Как ты «подхватываешь эмоцию» человека? (2-3 примера фраз)" },
    { s: "4) Структура типичного ответа", q: "Как ты добавляешь свой опыт так, чтобы это было к месту? (1-2 правила)" },
    { s: "4) Структура типичного ответа", q: "Что считать «конкретной мыслью» у тебя? (пример)" },
    { s: "4) Структура типичного ответа", q: "Когда ты задаешь вопрос в конце, а когда нет? (правило)" },
    { s: "5) Темы: логистика/траки/supply chain", q: "Как ты объясняешь сложное «простыми словами»? (2 правила)" },
    { s: "5) Темы: логистика/траки/supply chain", q: "Какие термины ты используешь, а какие избегаешь?" },
    { s: "5) Темы: логистика/траки/supply chain", q: "Дай 5 фраз, которые ты часто вставляешь в этой теме (в стиле Happens all the time)" },
    { s: "5) Темы: логистика/траки/supply chain", q: "Дай 1 образную мини-зарисовку как в примере про лед/траки (3-5 строк)" },
    { s: "5) Темы: AI/автоматизация/агенты", q: "Твоя позиция: где AI реально работает, а где хайп? (3-5 пунктов)" },
    { s: "5) Темы: AI/автоматизация/агенты", q: "Твои «3 тезиса-линиии» как в примере (технология останется, пузырь, данные)" },
    { s: "5) Темы: AI/автоматизация/агенты", q: "Дай 2 короткие фирменные формулировки на английском, как в примерах (типа bubble will pop…)" },
    { s: "5) Темы: стартапы/карьера/взрослость", q: "Три тезиса про работу и границы (лояльность, перегруз, здоровье)" },
    { s: "6) Юмор и интонация", q: "Уровень юмора 1-10: где ты?" },
    { s: "6) Юмор и интонация", q: "Какие темы можно шутить, а какие нельзя?" },
    { s: "6) Юмор и интонация", q: "Твой юмор больше: ирония над собой, над жизнью, над индустрией? (выбери)" },
    { s: "6) Юмор и интонация", q: "Напиши 3 коротких шутки в своем стиле (как Excel/еда/погода), по 2-4 строки" },
    { s: "7) Жизненные вопросы (личные)", q: "Какая твоя «одна правда про жизнь», которую ты часто видишь? (2-4 строки)" },
    { s: "7) Жизненные вопросы (личные)", q: "Что для тебя значит «doing well in life»? (2-4 строки)" },
    { s: "7) Жизненные вопросы (личные)", q: "Твоя позиция про дружбу/отношения и границы (2-6 строк)" },
    { s: "7) Жизненные вопросы (личные)", q: "Дай 3 примера коротких честных ответов на разные жизненные вопросы (ты сам выбери вопросы)" },
    { s: "8) Как отвечаю в спорах", q: "Что ты делаешь, чтобы не агрессировать? (2-3 правила)" },
    { s: "8) Как отвечаю в спорах", q: "Твоя связка «согласен и добавлю» в твоих словах: 3 шаблона фраз" },
    { s: "8) Как отвечаю в спорах", q: "На какую тему ты чаще споришь (AI/стартапы/индустрия)? И какой у тебя типовой аргумент?" },
    { s: "8) Как отвечаю в спорах", q: "Дай пример ответа в споре на 6-10 строк (как в примере про пузырь)" },
    { s: "9) Палитра фраз (строительные блоки)", q: "Напиши 15-25 «кирпичиков» фраз, которые звучат как ты (не обязательно штамповать)" },
    { s: "9) Палитра фраз (строительные блоки)", q: "Какие 10 фраз ты запрещаешь, потому что они «не ты»?" },
    { s: "10) Как взаимодействую с людьми", q: "Как ты поддерживаешь человека, когда ему тяжело, не скатываясь в терапию? (2-3 правила)" },
    { s: "10) Как взаимодействую с людьми", q: "Как ты не обесцениваешь, даже если человек «сам виноват»? (2-3 фразы)" },
    { s: "10) Как взаимодействую с людьми", q: "Как ты gently challenge-ишь мысль человека? (2-3 шаблона)" },
    { s: "10) Как взаимодействую с людьми", q: "Дай пример ответа на токсичную формулировку человека (как пример про «white trash friends»), но в твоем стиле" },
    { s: "11) Резюме стиля одним абзацем", q: "Напиши один абзац: кто ты, как звучишь, что человек чувствует после твоего ответа." },
    { s: "11) Резюме стиля одним абзацем", q: "Укажи 5 обязательных правил, которые всегда должны соблюдаться в твоих текстах." }
  ];
  var INTERVIEW_QUESTIONS_EN = [
    { s: "1) Who I am by legend (character)", q: "Where were you born and where are you 'by vibe'? (city/region, 1 line)" },
    { s: "1) Who I am by legend (character)", q: "When and why did you move? (year + 1-2 reasons)" },
    { s: "1) Who I am by legend (character)", q: "Were there countries/cities that greatly influenced you? (where you lived, how long, what changed)" },
    { s: "1) Who I am by legend (character)", q: "Where do you live now and how to refer to it safely? (city/region, acceptable formulations)" },
    { s: "1) Who I am by legend (character)", q: "Main project/achievement that gives you the right to 'speak on the topic': what was it, what problem did you solve, how did it end? (briefly)" },
    { s: "1) Who I am by legend (character)", q: "Was there an accelerator/program like YC? Which one and how to mention it correctly without flexing?" },
    { s: "1) Who I am by legend (character)", q: "In which 3-5 topics are you a real expert? (list)" },
    { s: "1) Who I am by legend (character)", q: "What do you do now? (project/company name, what it does, 1-2 sentences)" },
    { s: "1) Who I am by legend (character)", q: "Age, family status, children, everyday life: what of this can be mentioned and how? (without deanon)" },
    { s: "1) Who I am by legend (character)", q: "What 2-4 'human' details add depth? (hobbies, music, sports, games)" },
    { s: "1) Who I am by legend (character)", q: "Practices/habits like meditation: do you have any? which? how to talk about it calmly?" },
    { s: "1) Who I am by legend (character)", q: "Are there cultural things like festivals/communities (Burning Man): can you mention them, and how carefully?" },
    { s: "1) Who I am by legend (character)", q: "What facts about yourself do you only mention when it's really relevant, not in every post/answer? (list). Examples: 'raised investment', 'was in YC', 'built a big product'." },
    { s: "1) Who I am by legend (character)", q: "For 4 contexts (logistics/industry, startups/AI, life/burnout/family, music/games/hobbies): what 1-2 'experience anchors' do you insert in passing?" },
    { s: "2) General tone: how I speak", q: "How would you describe your tone in 3 words?" },
    { s: "2) General tone: how I speak", q: "What does 'conversational and warm' mean to you in text? (2-3 rules)" },
    { s: "2) General tone: how I speak", q: "What sentence length is natural for you? (short/medium/sometimes long)" },
    { s: "2) General tone: how I speak", q: "How direct are you on a scale of 1-10?" },
    { s: "2) General tone: how I speak", q: "How do you keep respect when someone is struggling or burning? (2-3 tricks)" },
    { s: "2) General tone: how I speak", q: "Humor: what kind of dry and calm humor is yours? (1-2 sentences)" },
    { s: "2) General tone: how I speak", q: "How do you usually enter an answer? (2-3 typical openings)" },
    { s: "2) General tone: how I speak", q: "Give 5 starter phrases that really sound like you (can be in English, as in the example)" },
    { s: "3) What I never do", q: "What 5 things do you never write (style/intonation/position)?" },
    { s: "3) What I never do", q: "What phrases or 'text smells' do you hate? (e.g. pomp, bureaucratese)" },
    { s: "3) What I never do", q: "What topics do you never touch? (list)" },
    { s: "3) What I never do", q: "How do you respond when someone pulls you into therapy/diagnoses? (2-3 safe formulations)" },
    { s: "3) What I never do", q: "What words from 'business English' do you definitely not use? (list)" },
    { s: "3) What I never do", q: "In what cases do you still mention status/experience, and how does it sound 'without flex'? (2-3 examples)" },
    { s: "3) What I never do", q: "What 'generic answers' do you forbid yourself? (like It depends) And what do you replace them with?" },
    { s: "4) Structure of a typical answer", q: "How many paragraphs usually? (range)" },
    { s: "4) Structure of a typical answer", q: "Your standard order: what comes first, second, third? (scheme)" },
    { s: "4) Structure of a typical answer", q: "How do you 'pick up on someone's emotion'? (2-3 example phrases)" },
    { s: "4) Structure of a typical answer", q: "How do you add your experience so it's relevant? (1-2 rules)" },
    { s: "4) Structure of a typical answer", q: "What counts as a 'concrete thought' for you? (example)" },
    { s: "4) Structure of a typical answer", q: "When do you ask a question at the end, and when not? (rule)" },
    { s: "5) Topics: logistics/trucks/supply chain", q: "How do you explain complex things simply? (2 rules)" },
    { s: "5) Topics: logistics/trucks/supply chain", q: "What terms do you use, and which do you avoid?" },
    { s: "5) Topics: logistics/trucks/supply chain", q: "Give 5 phrases you often insert in this topic (in the style of Happens all the time)" },
    { s: "5) Topics: logistics/trucks/supply chain", q: "Give 1 mini image like the ice/trucks example (3-5 lines)" },
    { s: "5) Topics: AI/automation/agents", q: "Your position: where does AI really work, and where is it hype? (3-5 points)" },
    { s: "5) Topics: AI/automation/agents", q: "Your '3 thesis lines' as in the example (technology stays, bubble, data)" },
    { s: "5) Topics: AI/automation/agents", q: "Give 2 short signature formulations in English, as in the examples (like bubble will pop…)" },
    { s: "5) Topics: startups/career/adulthood", q: "Three theses on work and boundaries (loyalty, overload, health)" },
    { s: "6) Humor and intonation", q: "Humor level 1-10: where are you?" },
    { s: "6) Humor and intonation", q: "What topics can you joke about, and which not?" },
    { s: "6) Humor and intonation", q: "Your humor is more: self-irony, over life, over industry? (choose)" },
    { s: "6) Humor and intonation", q: "Write 3 short jokes in your style (like Excel/food/weather), 2-4 lines each" },
    { s: "7) Life questions (personal)", q: "What is your 'one truth about life' that you often see? (2-4 lines)" },
    { s: "7) Life questions (personal)", q: "What does 'doing well in life' mean to you? (2-4 lines)" },
    { s: "7) Life questions (personal)", q: "Your position on friendship/relationships and boundaries (2-6 lines)" },
    { s: "7) Life questions (personal)", q: "Give 3 examples of short honest answers to different life questions (you choose the questions)" },
    { s: "8) How I respond in arguments", q: "What do you do to avoid aggression? (2-3 rules)" },
    { s: "8) How I respond in arguments", q: "Your 'agree and add' link in your words: 3 phrase templates" },
    { s: "8) How I respond in arguments", q: "What topic do you argue about most (AI/startups/industry)? And what's your typical argument?" },
    { s: "8) How I respond in arguments", q: "Give an example of an argument response in 6-10 lines (like the bubble example)" },
    { s: "9) Phrase palette (building blocks)", q: "Write 15-25 phrase 'bricks' that sound like you (no need to stamp)" },
    { s: "9) Phrase palette (building blocks)", q: "What 10 phrases do you forbid because they're 'not you'?" },
    { s: "10) How I interact with people", q: "How do you support someone when they're having a hard time, without sliding into therapy? (2-3 rules)" },
    { s: "10) How I interact with people", q: "How do you avoid devaluing, even when the person is 'at fault'? (2-3 phrases)" },
    { s: "10) How I interact with people", q: "How do you gently challenge someone's thought? (2-3 templates)" },
    { s: "10) How I interact with people", q: "Give an example of a response to a toxic formulation (like the 'white trash friends' example), but in your style" },
    { s: "11) Style summary in one paragraph", q: "Write one paragraph: who you are, how you sound, what a person feels after your answer." },
    { s: "11) Style summary in one paragraph", q: "List 5 mandatory rules that must always be followed in your texts." }
  ];
  var INTERVIEW_QUESTIONS = locale === 'en' ? INTERVIEW_QUESTIONS_EN : INTERVIEW_QUESTIONS_RU;
  var INTERVIEW_DRAFT_KEY = 'myvoices_author_interview_draft_' + locale;
  var interviewIndex = 0;
  var interviewAnswers = [];

  function getInterviewDraft() {
    try {
      var raw = localStorage.getItem(INTERVIEW_DRAFT_KEY);
      if (!raw) return null;
      var d = JSON.parse(raw);
      if (!d || typeof d.index !== 'number' || !Array.isArray(d.answers)) return null;
      if (d.index < 0 || d.index >= INTERVIEW_QUESTIONS.length) return null;
      return { index: d.index, answers: d.answers };
    } catch (e) { return null; }
  }
  function setInterviewDraft() {
    saveCurrentAnswer();
    var total = INTERVIEW_QUESTIONS.length;
    var answers = interviewAnswers.slice(0, total);
    while (answers.length < total) answers.push('');
    try { localStorage.setItem(INTERVIEW_DRAFT_KEY, JSON.stringify({ index: interviewIndex, answers: answers })); } catch (e) {}
  }
  function clearInterviewDraft() { try { localStorage.removeItem(INTERVIEW_DRAFT_KEY); } catch (e) {} }
  function openInterviewConfirm() {
    var el = document.getElementById('interview-confirm-modal');
    if (el) el.hidden = false;
  }
  function closeInterviewConfirm() {
    var el = document.getElementById('interview-confirm-modal');
    if (el) el.hidden = true;
  }
  function openInterviewResumeModal(draft) {
    var n = draft.index + 1;
    var total = INTERVIEW_QUESTIONS.length;
    var fmt = (tr.interview_resume_progress || 'У вас есть сохранённый прогресс (пройдено {0} из {1} вопросов). Продолжить с того места или пройти интервью заново?').replace('{0}', n).replace('{1}', total);
    var el = document.getElementById('interview-resume-text');
    if (el) el.textContent = fmt;
    el = document.getElementById('interview-resume-modal');
    if (el) el.hidden = false;
  }
  function closeInterviewResumeModal() {
    var el = document.getElementById('interview-resume-modal');
    if (el) el.hidden = true;
  }
  function openInterviewModal(draft) {
    var total = INTERVIEW_QUESTIONS.length;
    if (draft && draft.answers && draft.answers.length) {
      interviewIndex = Math.min(draft.index, total - 1);
      interviewAnswers = draft.answers.slice(0, total);
      while (interviewAnswers.length < total) interviewAnswers.push('');
    } else {
      interviewIndex = 0;
      interviewAnswers = new Array(total).fill('');
    }
    var el = document.getElementById('interview-modal');
    if (el) el.hidden = false;
    renderInterviewQuestion();
  }
  function closeInterviewModal(completed) {
    if (completed !== true) setInterviewDraft();
    var el = document.getElementById('interview-modal');
    if (el) el.hidden = true;
  }
  function saveCurrentAnswer() {
    var input = document.getElementById('interview-answer-input');
    if (input && interviewAnswers.length > 0 && interviewIndex >= 0 && interviewIndex < interviewAnswers.length) {
      interviewAnswers[interviewIndex] = input.value || '';
    }
  }
  function buildInterviewDocument() {
    var parts = [];
    var prevSection = '';
    INTERVIEW_QUESTIONS.forEach(function(item, i) {
      if (item.s !== prevSection) {
        parts.push('\n## ' + item.s + '\n');
        prevSection = item.s;
      }
      var ans = (interviewAnswers[i] || '').trim();
      parts.push((i + 1) + '. ' + item.q + '\n' + (ans ? ans + '\n' : '—\n'));
    });
    return parts.join('').trim();
  }
  function getInterviewTarget() {
    return document.getElementById('onboarding-author-history') || document.querySelector('#authors-wrap textarea[name="author_history"]');
  }
  function renderInterviewQuestion() {
    var total = INTERVIEW_QUESTIONS.length;
    var item = INTERVIEW_QUESTIONS[interviewIndex];
    var progressFill = document.getElementById('interview-progress-fill');
    var progressText = document.getElementById('interview-progress-text');
    var sectionLabel = document.getElementById('interview-section-label');
    var questionEl = document.getElementById('interview-question-title');
    var input = document.getElementById('interview-answer-input');
    var nextBtn = document.getElementById('interview-next');
    var pct = total ? Math.round(((interviewIndex + 1) / total) * 100) : 0;
    if (progressFill) progressFill.style.width = pct + '%';
    var minsLeft = Math.max(0, Math.ceil((total - interviewIndex - 1) * (30 / total)));
    var progressFmt = (tr.interview_question_progress_full || 'Вопрос {0} из {1} · осталось примерно {2} мин').replace('{0}', interviewIndex + 1).replace('{1}', total).replace('{2}', minsLeft);
    if (progressText) progressText.textContent = progressFmt;
    if (sectionLabel) sectionLabel.textContent = item.s;
    if (questionEl) questionEl.textContent = item.q;
    if (input) {
      input.value = interviewAnswers[interviewIndex] || '';
      input.placeholder = tr.interview_answer_placeholder || 'Ваш ответ...';
    }
    var prevBtn = document.getElementById('interview-prev');
    if (prevBtn) prevBtn.hidden = interviewIndex === 0;
    if (nextBtn) nextBtn.textContent = interviewIndex === total - 1 ? (tr.interview_finish || 'Завершить') : (tr.interview_next || 'Далее');
  }
  function interviewNext() {
    saveCurrentAnswer();
    if (interviewIndex >= INTERVIEW_QUESTIONS.length - 1) {
      clearInterviewDraft();
      var doc = buildInterviewDocument();
      var ta = getInterviewTarget();
      if (ta) ta.value = doc;
      closeInterviewModal(true);
      return;
    }
    interviewIndex++;
    renderInterviewQuestion();
  }
  function interviewPrev() {
    saveCurrentAnswer();
    if (interviewIndex > 0) {
      interviewIndex--;
      renderInterviewQuestion();
    }
  }
  function onInterviewConfirmYes() {
    closeInterviewConfirm();
    var draft = getInterviewDraft();
    if (draft) openInterviewResumeModal(draft);
    else openInterviewModal();
  }

  function attachInterviewListeners() {
    document.body.addEventListener('click', function(e) {
      var id = e.target && e.target.id;
      if (id === 'onboarding-btn-interview' || id === 'btn-author-interview') {
        e.preventDefault();
        openInterviewConfirm();
      }
    });
    var el = document.getElementById('interview-confirm-no');
    if (el) el.addEventListener('click', closeInterviewConfirm);
    el = document.getElementById('interview-confirm-yes');
    if (el) el.addEventListener('click', onInterviewConfirmYes);
    el = document.getElementById('interview-next');
    if (el) el.addEventListener('click', interviewNext);
    el = document.getElementById('interview-prev');
    if (el) el.addEventListener('click', interviewPrev);
    el = document.getElementById('interview-close');
    if (el) el.addEventListener('click', function() { closeInterviewModal(false); });
    el = document.getElementById('interview-modal');
    if (el) el.addEventListener('click', function(ev) { if (ev.target === el) closeInterviewModal(false); });
    el = document.getElementById('interview-confirm-modal');
    if (el) el.addEventListener('click', function(ev) { if (ev.target === el) closeInterviewConfirm(); });
    el = document.getElementById('interview-resume-continue');
    if (el) el.addEventListener('click', function() {
      var draft = getInterviewDraft();
      closeInterviewResumeModal();
      openInterviewModal(draft || undefined);
    });
    el = document.getElementById('interview-resume-restart');
    if (el) el.addEventListener('click', function() {
      clearInterviewDraft();
      closeInterviewResumeModal();
      openInterviewModal();
    });
    el = document.getElementById('interview-resume-modal');
    if (el) el.addEventListener('click', function(ev) { if (ev.target === el) closeInterviewResumeModal(); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attachInterviewListeners);
  } else {
    attachInterviewListeners();
  }
})();
