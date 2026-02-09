# QA Checklist — UI Redesign (2026)

Use this list to verify the UI refresh. **No business logic, routes, or API changes** were made.

## Keyboard & focus

- [ ] **Focus visible**: All interactive elements (buttons, links, inputs, selects) show a visible focus ring (e.g. purple `box-shadow`) when focused via Tab.
- [ ] **Posts drawer — focus trap**: With the post drawer open, Tab cycles only through elements inside the drawer (close, links, author select, goal select, Generate, copy links). Shift+Tab from first element goes to last; Tab from last goes to first.
- [ ] **Posts drawer — Esc**: Pressing Escape closes the drawer.
- [ ] **Posts drawer — restore focus**: After closing the drawer (Esc or backdrop or close button), focus returns to the post card or button that opened it.

## Accessibility

- [ ] **Drawer**: Has `role="dialog"`, `aria-modal="true"`, `aria-labelledby="view-post-modal-title"`. Close button has `aria-label="Закрыть"`.
- [ ] **LinkedIn icon (people)**: 44×44px minimum hit area, `aria-label="Профиль LinkedIn"`, `title="Профиль LinkedIn"`.
- [ ] **Kebab menus**: Trigger has `aria-label="Действия"`, `aria-expanded`, `aria-haspopup="true"`; menu has `role="menu"`, items `role="menuitem"`.
- [ ] **Confirm delete (companies)**: Modal has `role="dialog"`, `aria-modal="true"`, `aria-labelledby="company-delete-title"`.
- [ ] **Companies — keyboard/focus**: Company list rows are focusable (button for select); kebab has 44px hit area, `aria-haspopup="menu"`, `aria-expanded`, `aria-controls`; drawer has focus trap, Esc closes, focus restores to opener.
- [ ] **Companies — menu accessibility**: List and details kebab menus use `role="menu"` and `role="menuitem"`; Arrow Up/Down navigate items, Escape closes and returns focus to trigger.

## Companies page (split-view, drawer, states)

- [ ] **Companies — empty list**: «Добавь первую компанию» + CTA «Добавить компанию»; no list rows.
- [ ] **Companies — no results**: Search with no matches shows «Ничего не найдено» + «Сбросить»; «Сбросить» clears search and shows list.
- [ ] **Companies — error**: Fetch failure shows «Не удалось загрузить» + «Повторить»; «Повторить» refetches.
- [ ] **Companies — loading**: Skeleton lines in list pane while companies load.
- [ ] **Companies — Add/Edit in drawer**: Add/Edit company opens right drawer (not inline form); fields: Название (required), Сайт, LinkedIn компании; sticky footer «Сохранить» / «Отмена»; save disabled when invalid; URL format hints and validation.
- [ ] **Companies — no API/logic changes**: Same `/companies`, `/companies/{id}`, `/people?company_id=` usage; no new routes or backend changes.
- [ ] **Companies — no console errors**: Console clear on load, list, select company, open drawer, save, delete.

## Contrast & labels

- [ ] Text and backgrounds meet sufficient contrast (e.g. `--text` on `--surface` / `--bg`).
- [ ] Form labels are associated with inputs (`for` / `id` or wrapping).
- [ ] Loading / empty / error states use `aria-live` where appropriate (e.g. posts loading).

## States

- [ ] **Posts — loading**: Skeleton cards or loading message is shown while fetching.
- [ ] **Posts — empty**: Empty state with title, description, and CTA «Распознать по ссылке» is shown when there are no posts.
- [ ] **Posts — error**: Error message and «Повторить» button are shown on fetch failure.
- [ ] **Posts — drawer generate**: «Генерация…» (loading), then success (variants with Copy / Open) or error with retry.
- [ ] **People — LinkedIn validation**: Invalid LinkedIn URL (no `linkedin.com`) shows error message and disables Save until fixed.
- [ ] **Companies — delete**: Delete opens confirm modal with consequences text; Cancel closes, Удалить performs delete.

## Regression

- [ ] **No logic/API/route changes**: All endpoints, request/response shapes, and route paths are unchanged.
- [ ] **No JS errors**: Console is clear on load and during main flows (posts load, open drawer, generate reply, people list, company delete).
- [ ] **Desktop 1280–1440**: Layout is comfortable at 1280–1440px; no horizontal overflow or broken layout at smaller widths.
