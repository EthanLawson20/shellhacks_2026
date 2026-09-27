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

navigation?.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
  menuButton?.setAttribute('aria-expanded', 'false');
  menuButton?.setAttribute('aria-label', 'Open navigation');
  navigation.classList.remove('open');
}));

const scenarios = {
  one: {
    count: '01',
    label: 'area of interest',
    copy: 'A signal pattern suggests possible presence in Zone B. Responders would verify on site.',
    description: 'Simulated room map showing one possible presence near the center right'
  },
  two: {
    count: '02',
    label: 'areas of interest',
    copy: 'Separate signal patterns suggest possible presence in Zones A and C. Both areas would need verification.',
    description: 'Simulated room map showing two possible presence areas in Zones A and C'
  },
  clear: {
    count: '00',
    label: 'distinct patterns',
    copy: 'No distinct presence pattern appears in this scenario. An unclear reading does not confirm that a room is empty.',
    description: 'Simulated room map with no distinct presence pattern'
  }
};

const demoMap = document.getElementById('demo-map');
const resultNumber = document.getElementById('result-number');
const resultCopy = document.getElementById('result-copy');

document.querySelectorAll('.scenario').forEach((button) => {
  button.addEventListener('click', () => {
    const scenario = scenarios[button.dataset.scenario];
    if (!scenario) return;
    document.querySelectorAll('.scenario').forEach((option) => {
      const selected = option === button;
      option.classList.toggle('active', selected);
      option.setAttribute('aria-pressed', String(selected));
    });
    demoMap.dataset.scenario = button.dataset.scenario;
    demoMap.setAttribute('aria-label', scenario.description);
    resultNumber.innerHTML = `${scenario.count} <small>${scenario.label}</small>`;
    resultCopy.textContent = scenario.copy;
  });
});

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

