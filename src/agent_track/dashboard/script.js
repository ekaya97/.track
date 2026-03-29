let refreshInterval;
function startRefresh() {
    refreshInterval = setInterval(() => { if (!document.hidden) location.reload(); }, 5000);
}
startRefresh();
document.addEventListener('visibilitychange', () => {
    if (document.hidden) clearInterval(refreshInterval); else startRefresh();
});
