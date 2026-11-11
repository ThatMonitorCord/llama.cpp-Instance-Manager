const {test,expect} = require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'../../manager/web');
const defaults={schema:1,id:'local',name:'Workshop',port:5239,configured:true,login_start:true,instances_dir:'C:\\Instances',instances:[],peers:[]};
const instance={id:'one',name:'llama.cpp instance 1',gui_port:5240,api_port:9931,path:'C:\\Instances\\one\\LLama-GUI',install_state:'ready',online:true,running:true,preset:'Fast model',loaded_preset:'Fast model',auto_start:false,pid:1,sampled_at:10,status:{active_runtime:{generation:1,model:'model.gguf',port:9931}},metrics:'llamacpp:prompt_tokens_total 2388440\nllamacpp:tokens_predicted_total 499910\nllamacpp:prompt_seconds_total 10000\nllamacpp:tokens_predicted_seconds_total 10000\nllamacpp:requests_processing 2\nllamacpp:requests_deferred 1',slots:[{id:0,id_task:1,is_processing:true,n_ctx:128384,n_prompt_tokens:64558,next_token:{n_decoded:50}},{id:1,id_task:2,is_processing:true,n_ctx:128384,n_prompt_tokens:20,next_token:{n_decoded:1}}]};
async function fixture(page,{configured=true}={}){
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const config={...defaults,configured,instances:configured?[instance]:[]};const posts=[];
  await page.route('http://manager.test:5239/**',async route=>{
    const url=new URL(route.request().url()),name=url.pathname;
    if(name.startsWith('/api/')){
      if(route.request().method()==='POST'){
        const body=route.request().postDataJSON();posts.push({path:name,body});
        if(name==='/api/setup')Object.assign(config,body,{configured:true});
        return route.fulfill({json:{ok:true,job:'job1',port:5239}});
      }
      const data={
        '/api/config':config,
        '/api/fleet':{servers:[{...defaults,product:'llama.cpp-instance-manager',version:'0.1.0',local:true,online:true,instances:configured?[instance]:[],system:{system:{cpu:{percent:24},memory:{used_bytes:16*1073741824,total_bytes:64*1073741824},disk:{}},gpus:[{name:'NVIDIA RTX',vendor:'NVIDIA',utilization_percent:72,memory_used_bytes:12*1073741824,memory_total_bytes:24*1073741824,temperature_c:65}]}}],jobs:[]},
        '/api/discovery':{managers:[{id:'remote',name:'Living room',url:'http://192.168.1.20:5239'}]},
        '/api/ports':Array.from({length:Number(url.searchParams.get('count')||1)},(_,i)=>({name:`llama.cpp instance ${i+1}`,gui_port:5240+i,api_port:9931+i})),
        '/api/presets':['Fast model','Other model'],
        '/api/logs':{lines:['Starting llama-server','Model ready']}
      }[name];return route.fulfill({json:data??{}});
    }
    const file=path.join(root,name==='/'?'index.html':name);
    return route.fulfill({body:fs.readFileSync(file),contentType:name.endsWith('.css')?'text/css':name.endsWith('.js')?'application/javascript':name.endsWith('.png')?'image/png':'text/html'});
  });
  await page.goto('http://manager.test:5239/');return {errors,posts};
}
test('setup configures multiple independent instances and selects discovered peers',async({page})=>{
  const {errors,posts}=await fixture(page,{configured:false});
  await expect(page.locator('#setup-dialog')).toBeVisible();
  await page.locator('#setup-name').fill('Office server');await page.locator('#setup-count').fill('2');
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(page.locator('#setup-rows .port-row')).toHaveCount(2);
  if(process.env.CAPTURE_UI)await page.screenshot({path:'test-results/setup.png',fullPage:true});
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await page.locator('#setup-discovery input').check();
  await page.getByRole('button',{name:'Install instances',exact:true}).click();
  await expect(page.locator('#setup-dialog')).not.toBeVisible();
  const setup=posts.find(row=>row.path==='/api/setup');expect(setup.body.name).toBe('Office server');expect(setup.body.instances).toHaveLength(2);
  expect(posts.some(row=>row.path==='/api/connect')).toBe(true);expect(errors).toEqual([]);
});
test('monitor matches original structure, hides/restores cards, resets totals, and persists theme',async({page})=>{
  const {errors}=await fixture(page);await page.locator('[data-tab=monitor]').click();
  await expect(page.locator('[data-card=combined] [data-value=total]')).toHaveText('2,888,350 tokens');
  await expect(page.locator('[data-card="server/local"] .eyebrow')).toHaveText('Workshop');
  if(process.env.CAPTURE_UI)await page.screenshot({path:'test-results/monitor.png',fullPage:true});
  await page.locator('[data-card=combined]').getByRole('button',{name:'Reset session counters'}).click();
  await expect(page.locator('[data-card=combined] [data-value=total]')).toHaveText('0 tokens');
  await page.locator('[data-card="local/one"]').getByRole('button',{name:'Hide',exact:true}).click();
  await expect(page.locator('[data-card="local/one"]')).not.toBeVisible();
  await page.getByRole('button',{name:'Restore hidden cards'}).click();await expect(page.locator('[data-card="local/one"]')).toBeVisible();
  await page.locator('#theme').selectOption('mint');await page.reload();await expect(page.locator('html')).toHaveAttribute('data-theme','mint');expect(errors).toEqual([]);
});
test('startup saves chosen preset and model autostart; controls submit once',async({page})=>{
  const {errors,posts}=await fixture(page);await page.getByText('Startup & installation',{exact:true}).click();await page.getByRole('button',{name:'Startup settings',exact:true}).click();
  await page.locator('#startup-preset').selectOption('Other model');await page.locator('#startup-auto').check();await page.getByRole('button',{name:'Save startup settings'}).click();
  expect(posts.find(row=>row.path==='/api/startup').body).toEqual({instance_id:'one',preset:'Other model',auto_start:true});
  await page.getByRole('button',{name:'Restart',exact:true}).click();await expect(page.getByRole('button',{name:'Restart',exact:true})).toBeDisabled();expect(posts.filter(row=>row.path==='/api/action')).toHaveLength(1);expect(errors).toEqual([]);
});
test('mobile drawer closes with Escape and restores focus without horizontal overflow',async({page})=>{
  await page.setViewportSize({width:390,height:844});const {errors}=await fixture(page);await page.getByRole('button',{name:'Open navigation'}).click();await expect(page.locator('#sidebar')).toHaveClass(/open/);await page.keyboard.press('Escape');await expect(page.locator('#open-nav')).toBeFocused();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);expect(errors).toEqual([]);
});
