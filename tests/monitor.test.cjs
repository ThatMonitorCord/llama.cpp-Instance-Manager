const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const context=vm.createContext({window:{},console});
for(const file of ['vendor/inference-stats.js','monitor.js'])vm.runInContext(fs.readFileSync(`manager/web/${file}`,'utf8'),context);
const monitor=context.window.LlamaGui.managerMonitor;
test('combined inference adds every field directly, including rates and context',()=>{
  const a={session:{prompt:100,generated:20,total:120},context:{used:30,total:100,remaining:70},speed:{prompt:10,generated:5},requests:{processingBest:2,queued:3},slots:{busy:2,total:4}};
  const b={session:{prompt:200,generated:40,total:240},context:{used:50,total:200,remaining:150},speed:{prompt:20,generated:7},requests:{processingBest:1,queued:2},slots:{busy:1,total:8}};
  const total=monitor.sum([a,b]);
  assert.equal(total.session.total,360);assert.equal(total.speed.prompt,30);assert.equal(total.speed.generated,12);
  assert.equal(total.requests.processingBest,3);assert.equal(total.requests.queued,5);assert.equal(total.slots.total,12);
  assert.equal(total.context.used,80);assert.equal(total.context.total,300);assert.equal(total.context.remaining,220);
  assert.equal(total.context.percent,80/300*100);
});
test('same instance identity is never counted twice',()=>{
  const instance={id:'one',online:true,running:true,pid:1,sampled_at:1,status:{active_runtime:{generation:1}},metrics:'llamacpp:prompt_tokens_total 100\nllamacpp:tokens_predicted_total 50',slots:[]};
  const servers=monitor.collect([{id:'server',online:true,instances:[instance,instance]}]);
  assert.equal(servers[0].snapshot.session.total,150);assert.equal(servers[0].instances.length,1);
});
test('reset establishes new baselines without touching upstream counters',()=>{
  const instance={id:'reset',online:true,running:true,pid:2,sampled_at:1,status:{active_runtime:{generation:1}},metrics:'llamacpp:prompt_tokens_total 100\nllamacpp:tokens_predicted_total 50',slots:[]};
  const server={id:'s',online:true,instances:[instance]};monitor.collect([server]);monitor.reset(['s/reset']);
  assert.equal(monitor.collect([server])[0].snapshot.session.total,0);
  instance.sampled_at=2;instance.metrics='llamacpp:prompt_tokens_total 105\nllamacpp:tokens_predicted_total 60';
  assert.equal(monitor.collect([server])[0].snapshot.session.total,15);
});
