const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const playerSource = fs.readFileSync(
    path.join(__dirname, "../static/src/js/lms_player.js"), "utf8"
);

function playerHarness() {
    const listeners = {};
    const requests = [];
    let tick;
    const video = {
        currentTime: 0,
        duration: 100,
        paused: false,
        playbackRate: 1,
        addEventListener(name, callback) { listeners[name] = callback; },
        pause() { this.paused = true; },
    };
    const feedback = {textContent: "", classList: {toggle() {}}};
    const retry = {hidden: true, addEventListener(name, callback) { listeners[`retry:${name}`] = callback; }};
    const elements = {
        lmsPlayerPage: {dataset: {lessonId: "12", heartbeatUrl: "/lms/video/heartbeat", lastPosition: "0", completed: "0", guardSeek: "1"}},
        lmsVideoPlayer: video,
        lmsPlaybackPosition: {textContent: ""},
        lmsSavedPosition: {textContent: ""},
        lmsPlayerFeedback: feedback,
        lmsRetryProgress: retry,
    };
    const document = {readyState: "complete", getElementById(id) { return elements[id]; }, addEventListener() {}};
    const window = {setInterval(callback) { tick = callback; }, addEventListener() {}};
    function fetch(url, options) {
        return new Promise((resolve, reject) => requests.push({url, options, resolve, reject}));
    }
    vm.runInNewContext(playerSource, {document, window, fetch});
    return {video, listeners, requests, feedback, retry, tick: () => tick()};
}

function accept(request, position, completed = false) {
    request.resolve({ok: true, json: async () => ({result: {
        status: "success", allowed_position: position, is_completed: completed,
    }})});
}

async function settled() {
    await new Promise(setImmediate);
}

test("sends the final playback position after an in-flight heartbeat", async () => {
    const player = playerHarness();
    player.video.duration = 10;
    player.video.currentTime = 5;
    player.tick();
    assert.equal(player.requests.length, 1);

    player.video.currentTime = 10;
    player.video.paused = true;
    player.listeners.ended();
    player.listeners.pause();
    assert.equal(player.requests.length, 1);

    accept(player.requests[0], 5);
    await settled();
    assert.equal(player.requests.length, 2);
    assert.equal(JSON.parse(player.requests[1].options.body).params.current_time, 10);

    accept(player.requests[1], 10, true);
    await settled();
    assert.equal(player.requests.length, 2);
    assert.match(player.feedback.textContent, /Lesson complete/);
});

test("does not repeat a forced save after the in-flight request completes the lesson", async () => {
    const player = playerHarness();
    player.video.currentTime = 95;
    player.tick();
    player.video.currentTime = 100;
    player.listeners.ended();
    accept(player.requests[0], 95, true);
    await settled();
    assert.equal(player.requests.length, 1);
});
