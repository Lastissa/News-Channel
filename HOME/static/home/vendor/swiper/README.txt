Swiper 11.2.10 (MIT). Custom build: core + Autoplay + Keyboard + A11y + EffectFade.
Self hosted on purpose (no CDN request, works with WhiteNoise, one less third party at runtime).

Rebuild:
  npm i swiper@11 esbuild
  entry.js:
    import Swiper from 'swiper';
    import { Autoplay, Keyboard, A11y, EffectFade } from 'swiper/modules';
    Swiper.use([Autoplay, Keyboard, A11y, EffectFade]);
    window.Swiper = Swiper;
  npx esbuild entry.js --bundle --minify --format=iife --target=es2018 --outfile=swiper.custom.min.js
  cat node_modules/swiper/swiper.css node_modules/swiper/modules/effect-fade.css > raw.css
  npx esbuild raw.css --minify --outfile=swiper.custom.min.css
