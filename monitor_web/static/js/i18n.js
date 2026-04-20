// i18n.js
const I18n = {
  lang: localStorage.getItem('lang') || 'zh',
  translations: {},

  async init() {
    try {
      const res = await fetch(`/static/i18n/${this.lang}.json`);
      this.translations = await res.json();
      this.apply();
      document.documentElement.lang = this.lang;
    } catch (e) {
      console.warn('i18n: failed to load', this.lang, e);
    }
  },

  t(key) {
    const keys = key.split('.');
    let val = this.translations;
    for (const k of keys) val = val?.[k];
    return val || key;
  },

  async switchLang() {
    this.lang = this.lang === 'zh' ? 'en' : 'zh';
    localStorage.setItem('lang', this.lang);
    await this.init();
  },

  apply() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      el.textContent = this.t(key);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const key = el.getAttribute('data-i18n-placeholder');
      el.placeholder = this.t(key);
    });
  }
};

window.I18n = I18n;
