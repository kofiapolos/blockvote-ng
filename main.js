// BlockVote NG — Main JavaScript

// Auto-dismiss flash messages
document.addEventListener('DOMContentLoaded', () => {
    const flashes = document.querySelectorAll('.flash');
    flashes.forEach(flash => {
        setTimeout(() => {
            flash.style.opacity = '0';
            flash.style.transform = 'translateY(-8px)';
            flash.style.transition = 'all 0.4s ease';
            setTimeout(() => flash.remove(), 400);
        }, 5000);
    });
});
