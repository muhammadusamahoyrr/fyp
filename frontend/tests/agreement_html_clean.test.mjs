/* The browser's second layer for rich agreement bodies (lib/agreementHtml.js).
 *
 * The server sanitises a rich body before it is stored; this is what every
 * viewer runs again before putting it into the page. Same allowlist. */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>");
globalThis.DOMParser = dom.window.DOMParser;

const { cleanAgreementHtml, textToAgreementHtml, agreementPlainText } =
    await import("../src/lib/agreementHtml.js");

test("the toolbar's formatting survives", () => {
    const body = '<h2>Rent</h2><p style="text-align:center"><b>Due</b> <i>now</i> <u>u</u> <s>s</s></p>'
        + "<ul><li>one</li></ul><blockquote>q</blockquote><hr>";
    assert.equal(cleanAgreementHtml(body), body);
});

test("scripts, handlers, links, images and frames are removed", () => {
    const out = cleanAgreementHtml(
        '<p onclick="x()">hi</p><script>alert(1)</script><img src=x onerror=alert(1)>'
        + '<a href="javascript:alert(1)">link</a><iframe src="http://x"></iframe><style>p{}</style>');
    for (const bad of ["onclick", "script", "alert", "img", "javascript", "iframe", "<style", "href"]) {
        assert.ok(!out.includes(bad), `"${bad}" survived: ${out}`);
    }
    assert.ok(out.includes("hi") && out.includes("link"), "the words should stay");
});

test("only alignment survives in a style", () => {
    assert.equal(cleanAgreementHtml('<p style="color:red;text-align:right;background:url(x)">x</p>'),
                 '<p style="text-align:right">x</p>');
});

test("without a DOM it returns escaped text, never markup", async () => {
    const saved = globalThis.DOMParser;
    delete globalThis.DOMParser;
    try {
        const out = cleanAgreementHtml("<b>x</b><script>y</script>");
        assert.ok(!out.includes("<"), out);
    } finally { globalThis.DOMParser = saved; }
});

test("a template's plain text becomes escaped paragraphs", () => {
    assert.equal(textToAgreementHtml("A < B\r\n\r\nC & D"), "<p>A &lt; B</p><p>C &amp; D</p>");
});

test("plain text reads the words", () => {
    assert.equal(agreementPlainText("<p>Pay <b>Rs 5</b></p><p>&lt;now&gt;</p>"), "Pay Rs 5 <now>");
    assert.equal(agreementPlainText("<p><br></p>"), "");
});

test("colour, size, font, sub/sup and safe links survive in one form", () => {
    const out = cleanAgreementHtml(
        '<p><span style="color:#FF0000;font-size:18px;font-family:Arial, sans-serif;position:fixed">r</span>'
        + ' H<sub>2</sub>O x<sup>2</sup> <a href="https://x.pk" onclick="z()">ok</a> <a href="javascript:alert(1)">bad</a></p>');
    assert.ok(out.includes('<span style="font-family:arial;font-size:18px;color:#ff0000">r</span>'), out);
    assert.ok(out.includes("<sub>2</sub>") && out.includes("<sup>2</sup>"));
    assert.ok(out.includes('href="https://x.pk"') && out.includes('rel="noopener noreferrer"'));
    assert.ok(!out.includes("javascript") && !out.includes("onclick") && !out.includes("fixed"));
});
