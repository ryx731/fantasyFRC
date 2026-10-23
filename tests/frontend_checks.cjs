'use strict';

// Exercise the actual browser script without a server, browser, or dependencies.
// These stubs only supply the DOM surface needed for state and request races.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8');
const reply = (status, data) => ({ status, ok: status >= 200 && status < 300, json: async () => data });
const deferred = () => {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return { promise, resolve };
};
const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

function browser({ stored = {}, fetch: fetchImpl, storageBlocked = false } = {}) {
    const elements = new Map(), store = new Map(Object.entries(stored)), intervals = new Map();
    const requests = [], listeners = new Map();
    let timer = 0;
    const document = {
        hidden: false,
        documentElement: { dataset: {} },
        activeElement: null,
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, element(id));
            return elements.get(id);
        },
        querySelector(selector) {
            const choice = selector.match(/^\[data-theme-choice="([\w-]+)"\]$/)?.[1];
            if (choice) return document.getElementById('themes').querySelector(selector);
            return document.getElementById(selector);
        },
        querySelectorAll(selector) {
            if (selector === '[data-theme-choice]') return [...themeButtons()];
            return [];
        },
        addEventListener(name, callback) { listeners.set(name, callback); },
        createElement(name) { return element(name); },
        head: { appendChild() {} },
    };
    const themeElements = new Map();
    function themeButtons() {
        const html = document.getElementById('themes').innerHTML;
        const tags = [...html.matchAll(/<button\b([^>]*\bdata-theme-choice="([^"]+)"[^>]*)>/g)];
        return tags.map(([, attributes, id]) => {
            if (!themeElements.has(id)) {
                const button = element(`theme-${id}`);
                button.dataset.themeChoice = id;
                button.dataset.action = 'theme';
                button.attributes['aria-pressed'] = attributes.match(/aria-pressed="([^"]+)"/)?.[1];
                themeElements.set(id, button);
            }
            return themeElements.get(id);
        });
    }
    function element(id) {
        let html = '';
        return {
            id, hidden: false, disabled: false, open: false, value: '', textContent: '',
            get innerHTML() { return html; },
            set innerHTML(value) { html = value; if (id === 'themes') themeElements.clear(); },
            className: '', dataset: {}, attributes: {}, events: new Map(),
            style: { setProperty() {} },
            classList: { add() {}, remove() {}, toggle() {} },
            addEventListener(name, callback) { this.events.set(name, callback); },
            setAttribute(name, value) { this.attributes[name] = String(value); },
            getAttribute(name) { return this.attributes[name]; },
            removeAttribute(name) { delete this.attributes[name]; },
            querySelector(selector) {
                const choice = selector.match(/^\[data-theme-choice="([\w-]+)"\]$/)?.[1];
                if (choice) return themeButtons().find(button => button.dataset.themeChoice === choice);
                return element(`${id}:${selector}`);
            },
            querySelectorAll(selector) {
                if (id === 'themes' && (selector === '[data-theme-choice]' || selector === '.theme-choice')) return themeButtons();
                return [];
            },
            focus() { document.activeElement = this; },
            showModal() { this.open = true; },
            close() { this.open = false; },
        };
    }
    const context = vm.createContext({
        document, location: { hash: '' }, navigator: { clipboard: { writeText: async () => {} } },
        localStorage: {
            getItem(key) { if (storageBlocked) throw new Error('Storage blocked'); return store.get(key) ?? null; },
            setItem(key, value) { if (storageBlocked) throw new Error('Storage blocked'); store.set(key, String(value)); },
            removeItem(key) { if (storageBlocked) throw new Error('Storage blocked'); store.delete(key); },
        },
        fetch: async (url, options) => {
            requests.push({ url, options });
            const result = fetchImpl?.(url, options);
            if (result !== undefined) return result;
            return reply(200, url === '/api/auth/config' ? {} : []);
        },
        setTimeout: () => ++timer, clearTimeout() {},
        setInterval(callback) { const id = ++timer; intervals.set(id, callback); return id; },
        clearInterval(id) { intervals.delete(id); },
        URLSearchParams, console,
    });
    context.window = context;
    context.addEventListener = (name, callback) => listeners.set(name, callback);
    vm.runInContext(source, context, { filename: 'static/app.js' });
    return {
        context, document, store, requests, intervals, elements, listeners,
        run: code => vm.runInContext(code, context),
    };
}

test('every appearance choice can be selected from every other theme', async () => {
    const b = browser();
    await settle();
    b.run("user={username:'manager',user_id:1};token='token';location.hash='#profile';route()");
    const ids = Array.from(b.run('themes.map(choice => choice.id)'));
    assert.equal(new Set(ids).size, ids.length);
    const choose = async id => {
        b.context.choice = b.document.querySelector(`[data-theme-choice="${id}"]`);
        b.context.choice.focus();
        await b.run('actions.theme(choice)');
    };
    for (const from of ids) for (const to of ids) {
        await choose(from);
        await choose(to);
        assert.equal(b.document.documentElement.dataset.theme, to, `${from} → ${to}`);
        assert.equal(b.store.get('frc_theme'), to);
        const selected = b.document.querySelectorAll('[data-theme-choice]').filter(el => el.getAttribute('aria-pressed') === 'true');
        assert.equal(selected.length, 1, 'Exactly one appearance choice should be selected');
        assert.equal(selected[0].dataset.themeChoice, to);
        assert.equal(b.document.activeElement.dataset.themeChoice, to);
    }
});

test('a current expired session signs out and dismisses its modal', async () => {
    const b = browser({ fetch: url => url === '/expired' ? reply(401, { detail: 'Expired' }) : undefined });
    await settle();
    b.run("token='expired-token';user={username:'manager',user_id:1};showModal('Confirm', '<p>Pending action</p>')");
    await assert.rejects(b.run("api('/expired')"), /session expired/i);
    assert.equal(b.run('token'), null);
    assert.equal(b.run('user'), null);
    assert.equal(b.document.getElementById('modal').open, false);
    assert.equal(b.document.getElementById('gate').hidden, false);
});

test('an old unauthorized response cannot sign out a replacement session', async () => {
    const pending = deferred();
    const b = browser({ fetch: url => url === '/old-request' ? pending.promise : undefined });
    await settle();
    b.run("token='old-token';user={username:'old-manager',user_id:1}");
    const request = b.run("api('/old-request')");
    b.run("token='new-token';user={username:'new-manager',user_id:2}");
    pending.resolve(reply(401, { detail: 'Expired' }));
    await assert.rejects(request);
    assert.equal(b.run('token'), 'new-token');
    assert.equal(b.run('user.username'), 'new-manager');
    assert.equal(b.requests.find(r => r.url === '/old-request').options.headers.Authorization, 'Bearer old-token');
});

test('startup account validation cannot replace a newer signed-in account', async () => {
    const pending = deferred();
    const b = browser({
        stored: { frc_token: 'old-token', frc_user: JSON.stringify({ username: 'old-manager', user_id: 1 }) },
        fetch: url => url === '/api/auth/me' ? pending.promise : undefined,
    });
    await settle();
    b.run("signedIn({access_token:'new-token',username:'new-manager',user_id:2,is_admin:false})");
    pending.resolve(reply(200, { username: 'old-manager', user_id: 1, is_admin: true }));
    await settle();
    assert.equal(b.run('token'), 'new-token');
    assert.equal(b.run('user.username'), 'new-manager');
    assert.equal(JSON.parse(b.store.get('frc_user')).username, 'new-manager');
});

test('navigation dismisses confirmations that belong to the previous page', async () => {
    const b = browser();
    await settle();
    b.run("token='token';user={username:'manager',user_id:1};showModal('Confirm league action','<p>League A</p>');location.hash='#profile';route()");
    assert.equal(b.document.getElementById('modal').open, false);
    assert.equal(b.document.getElementById('profile').hidden, false);
});

test('late league-list responses cannot overwrite a newer page', async () => {
    const pending = deferred();
    const b = browser({ fetch: url => url === '/api/leagues' ? pending.promise : undefined });
    await settle();
    b.run("token='token';user={username:'manager',user_id:1};location.hash='#leagues'");
    const oldRoute = b.run('route()');
    await b.run("location.hash='#profile';route()");
    pending.resolve(reply(200, []));
    await oldRoute;
    assert.equal(b.document.getElementById('profile').hidden, false);
    assert.equal(b.document.getElementById('dashboard').hidden, true);
    assert.doesNotMatch(b.document.getElementById('dashboard').innerHTML, /Your first league starts here/);
});

test('appearance and sign-in keep working when browser storage is unavailable', async () => {
    const b = browser({ storageBlocked: true });
    await settle();
    await b.run("theme('light');signedIn({access_token:'visit-token',username:'manager',user_id:1})");
    await settle();
    assert.equal(b.document.documentElement.dataset.theme, 'light');
    assert.equal(b.run('token'), 'visit-token');
    assert.equal(b.run('user.username'), 'manager');
    b.run('logout()');
    assert.equal(b.run('token'), null);
    assert.equal(b.document.getElementById('gate').hidden, false);
});

test('late score views and finalize confirmations stay closed after navigation', async () => {
    for (const action of ['score-detail', 'finalize']) {
        const pending = deferred();
        const b = browser({ fetch: url => url.includes('/periods/1/scores') ? pending.promise : undefined });
        await settle();
        b.run("token='token';user={username:'manager',user_id:1};league={id:1,rosters:[],periods:[]}");
        const oldAction = b.run(`actions[${JSON.stringify(action)}]({dataset:{week:'1'}})`);
        await b.run("location.hash='#profile';route()");
        pending.resolve(reply(200, []));
        await oldAction;
        assert.equal(b.document.getElementById('modal').open, false, `${action} should not open on a newer page`);
        assert.equal(b.document.getElementById('profile').hidden, false);
    }
});

test('draft refreshes cannot overlap and reverse the displayed pick order', async () => {
    const pending = deferred();
    const league = {
        id: 1, owner_id: 1, name: 'Test league', my_team_name: 'Manager one',
        member_count: 2, max_teams: 2, roster_size: 1, playoff_teams: 0, draft_status: 'ACTIVE',
        draft: { status: 'ACTIVE', current_picker_id: 1, current_picker_name: 'Manager one', current_pick_index: 0, total_picks: 2, sequence: [1, 2] },
        rosters: [{ id: 1, user_id: 1, name: 'Manager one', teams: [] }, { id: 2, user_id: 2, name: 'Manager two', teams: [] }],
        activity: [], periods: [],
    };
    let calls = 0;
    const b = browser({ fetch: url => {
        if (url !== '/api/leagues/1') return undefined;
        calls++;
        return calls === 1 ? reply(200, league) : pending.promise;
    } });
    await settle();
    await b.run("token='token';user={username:'manager',user_id:1};location.hash='#league/1/draft';route()");
    assert.equal(b.intervals.size, 1);
    const poll = [...b.intervals.values()][0];
    const firstPoll = poll();
    await poll();
    assert.equal(calls, 2, 'Only one background refresh should be in flight');
    const next = { ...league, draft: { ...league.draft, current_pick_index: 1, current_picker_id: 2 } };
    pending.resolve(reply(200, next));
    await firstPoll;
    assert.equal(b.run('league.draft.current_pick_index'), 1);
});
