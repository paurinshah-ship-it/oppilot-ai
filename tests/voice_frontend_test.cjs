const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements={};let canceled=0,spoken=0, released=0;
const sandbox={console,Float32Array,ArrayBuffer,DataView,Uint8Array,Math,Number,String,
 btoa:s=>Buffer.from(s,'binary').toString('base64'),
 document:{getElementById:id=>elements[id]??=( {textContent:'',disabled:false,value:'18'}),body:{scrollHeight:300},addEventListener(){}},
 parent:{postMessage(){}},window:{addEventListener(){}},navigator:{},crypto:{randomUUID:()=> 'new-session'},
 speechSynthesis:{cancel(){canceled++},getVoices(){return [{localService:true,lang:'en-US'}]},speak(){spoken++}},
 SpeechSynthesisUtterance:function(text){this.text=text;}};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('voice_frontend/voice.js','utf8'),sandbox);
vm.runInContext("scope='s';session='session';active=true;turn=2;receiveResponse({scope:'s',session:'session',turn:1,text:'stale'});",sandbox);
assert.equal(spoken,0);
vm.runInContext("receiveResponse({scope:'s',session:'session',turn:2,text:'current',transcript:'question'});",sandbox);
assert.equal(spoken,1);
vm.runInContext("receiveResponse({scope:'s',session:'session',turn:2,text:'duplicate'});",sandbox);
assert.equal(spoken,1);
vm.runInContext("$('interrupt').onclick();receiveResponse({scope:'s',session:'session',turn:2,text:'stale'});",sandbox);
assert.equal(spoken,1);assert(canceled>=2);
vm.runInContext("stop();receiveResponse({scope:'s',session:'session',turn:3,text:'stopped'});",sandbox);
assert.equal(spoken,1);
// VAD speech onset interrupts playback before transcription completes.
vm.runInContext("active=true;ctx={sampleRate:16000};reset();process(new Float32Array(2048).fill(.1));process(new Float32Array(2048).fill(.1));",sandbox);
assert(vm.runInContext('speech',sandbox));assert(canceled>=4);
const wav=vm.runInContext('encodeWav([new Float32Array(48000).fill(.1)],48000)',sandbox);
assert.equal(Buffer.from(wav,'base64').length,32044);
console.log('Voice frontend checks passed: stale replies, duplicates, interruption, stop, speech onset, WAV resampling.');
