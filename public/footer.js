const footerId = "custom-footer";
const styleId = "custom-footer-style";

const cssStyles = `
#${footerId} {
    position: fixed;
    bottom: 10px;
    right: 20px;
    z-index: 2147483647;
    pointer-events: none;
    font-size: 12px;
    color: #6b7280;
    text-align: right;
    font-family: sans-serif;
    background-color: transparent;
    display: block;
    transition: opacity 0.3s ease-in-out;
}

#${footerId} a {
    pointer-events: auto;
    color: #2563eb;
    font-weight: bold;
    text-decoration: none;
}

#${footerId} a:hover {
    text-decoration: underline;
}

@media (max-width: 640px) {
    #${footerId} {
        bottom: 15px;
        right: 10px;
        font-size: 10px;
        background-color: rgba(255, 255, 255, 0.8);
        padding: 4px;
        border-radius: 4px;
        backdrop-filter: blur(2px);
    }
}
`;

function injectStyles() {
    if (document.getElementById(styleId)) return;

    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = cssStyles;
    document.head.appendChild(style);
}

function createFooterElement() {
    const div = document.createElement("div");

    div.id = footerId;

    div.innerHTML = `
        Made with 💙 by
        <a
            href="https://www.linkedin.com/in/pranavchoubey89/"
            target="_blank"
            rel="noopener noreferrer"
        >
            PRANAV
        </a>
    `;

    return div;
}

function checkVisibility() {
    const footer = document.getElementById(footerId);

    if (!footer) return;

    const messages = document.querySelectorAll(
        ".step, .cl-step, .message-content"
    );

    footer.style.opacity = messages.length > 0 ? "0" : "1";
    footer.style.pointerEvents = messages.length > 0 ? "none" : "auto";
}

function ensureFooter() {
    injectStyles();

    if (!document.getElementById(footerId)) {
        document.body.appendChild(createFooterElement());
    }

    checkVisibility();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureFooter);
} else {
    ensureFooter();
}