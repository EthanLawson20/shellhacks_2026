import { inject } from '@vercel/analytics';

inject();

const sceneStage = document.getElementById('scene-stage');
if (sceneStage) {
  import('./scene.js').catch((error) => {
    sceneStage.classList.add('webgl-failed');
    console.warn('3D room unavailable.', error);
  });
}

const menuButton = document.querySelector('.menu-toggle');
const navigation = document.querySelector('.nav');

menuButton?.addEventListener('click', () => {
  const isOpen = menuButton.getAttribute('aria-expanded') === 'true';
  menuButton.setAttribute('aria-expanded', String(!isOpen));
  menuButton.setAttribute('aria-label', isOpen ? 'Open navigation' : 'Close navigation');
  navigation.classList.toggle('open', !isOpen);
});

navigation?.querySelectorAll('a, button').forEach((link) => link.addEventListener('click', () => {
  menuButton?.setAttribute('aria-expanded', 'false');
  menuButton?.setAttribute('aria-label', 'Open navigation');
  navigation.classList.remove('open');
}));

const revealElements = document.querySelectorAll('.reveal');
if ('IntersectionObserver' in window && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08, rootMargin: '0px 0px -30px 0px' });
  revealElements.forEach((element) => observer.observe(element));
} else {
  revealElements.forEach((element) => element.classList.add('visible'));
}

const contactDialog = document.getElementById('contact-dialog');
document.querySelectorAll('[data-contact-open]').forEach((button) => button.addEventListener('click', () => contactDialog?.showModal()));
contactDialog?.querySelector('[data-contact-close]')?.addEventListener('click', () => contactDialog.close());
contactDialog?.addEventListener('click', (event) => {
  if (event.target === contactDialog) contactDialog.close();
});
contactDialog?.querySelectorAll('[data-copy]').forEach((button) => button.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    button.textContent = 'Copied';
  } catch {
    button.textContent = 'Select to copy';
  }
  setTimeout(() => { button.textContent = 'Copy'; }, 1600);
}));

// Section labels (e.g. "05 USER CASE") scroll back to the top of the page.
const scrollToTop = () => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });
};
document.querySelectorAll('main section .section-kicker').forEach((kicker) => {
  kicker.classList.add('kicker-to-top');
  kicker.setAttribute('role', 'link');
  kicker.setAttribute('tabindex', '0');
  kicker.setAttribute('title', 'Back to top');
  kicker.addEventListener('click', scrollToTop);
  kicker.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      scrollToTop();
    }
  });
});
