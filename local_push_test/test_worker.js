'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const events={},shown=[];
let navigated=0,closed=0;
const sandbox={URL,self:{location:{origin:'http://127.0.0.1:18114'},
  addEventListener:(type,callback)=>events[type]=callback,
  registration:{showNotification:async(title,options)=>shown.push({title,options})},
  clients:{matchAll:async()=>[{url:'http://127.0.0.1:18114/',navigate:async()=>{navigated++;},focus:async()=>{}}],openWindow:async()=>{navigated++;}},
  skipWaiting:()=>{},},fetch:()=>{throw new Error('Acknowledgement must not call a document API');}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'sw.js'),'utf8'),sandbox);
(async()=>{
  let work;
  events.push({data:{json:()=>({kind:'request',tag:'test'})},waitUntil:promise=>work=promise});
  await work;
  assert.equal(shown[0].options.requireInteraction,true);
  assert.equal(shown[0].options.actions[0].action,'acknowledge');
  assert.equal(shown[0].options.actions[0].title,'확인');
  events.notificationclick({action:'acknowledge',notification:{close:()=>closed++},waitUntil:()=>{throw new Error('Acknowledgement must not open a page');}});
  assert.equal(closed,1);assert.equal(navigated,0);
  events.notificationclick({action:'',notification:{close:()=>closed++},waitUntil:promise=>work=promise});
  await work;assert.equal(closed,2);assert.equal(navigated,1);
  process.stdout.write('Interaction request and acknowledgement-only dismissal passed.\n');
})().catch(error=>{process.stderr.write(String(error));process.exitCode=1;});
