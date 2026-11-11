const {defineConfig} = require('@playwright/test');
module.exports = defineConfig({
  testDir:'tests/browser', timeout:30000, fullyParallel:true,
  use:{headless:true, screenshot:'only-on-failure'},
  reporter:'list'
});
