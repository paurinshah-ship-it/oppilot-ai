/* No SpeechRecognition/cloud service, external assets, or audio persistence. */
const $ = id => document.getElementById(id);
const send = (type, extra={}) => parent.postMessage({isStreamlitMessage:true,type,...extra}, '*');
let scope=null, ready=false, active=false, session='', turn=0, lastReply='', stream, ctx, processor, source;
let frames=[], preRoll=[], speech=false, voiced=0, quiet=0, onset=0, total=0;
const status = text => { $('status').textContent=text; resize(); };
const resize = () => send('streamlit:setFrameHeight',{height:document.body.scrollHeight+8});
function invalidate(){ turn++; speechSynthesis.cancel(); }
function reset(){frames=[];preRoll=[];speech=false;voiced=0;quiet=0;onset=0;total=0;}
function stop(message='Voice stopped. Microphone released.'){
  active=false; invalidate(); reset();
  if(processor){processor.onaudioprocess=null;processor.disconnect();processor=null;}
  if(source){source.disconnect();source=null;}
  if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;}
  if(ctx){ctx.close();ctx=null;}
  $('start').disabled=!ready; $('stop').disabled=true; $('interrupt').disabled=true;status(message);
}
function encodeWav(chunks, rate){
  const length=chunks.reduce((n,x)=>n+x.length,0), input=new Float32Array(length);
  let offset=0;for(const c of chunks){input.set(c,offset);offset+=c.length;}
  const count=Math.floor(length*16000/rate), buffer=new ArrayBuffer(44+count*2), view=new DataView(buffer);
  const ascii=(o,s)=>[...s].forEach((c,i)=>view.setUint8(o+i,c.charCodeAt(0)));
  ascii(0,'RIFF');view.setUint32(4,36+count*2,true);ascii(8,'WAVEfmt ');view.setUint32(16,16,true);
  view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);ascii(36,'data');view.setUint32(40,count*2,true);
  for(let i=0;i<count;i++){
    const begin=Math.floor(i*rate/16000), end=Math.max(begin+1,Math.floor((i+1)*rate/16000));
    let sum=0;for(let j=begin;j<Math.min(end,length);j++)sum+=input[j];
    const v=Math.max(-1,Math.min(1,sum/(Math.min(end,length)-begin)));
    view.setInt16(44+i*2,v<0?v*32768:v*32767,true);
  }
  let binary='';const bytes=new Uint8Array(buffer);
  for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return btoa(binary);
}
function process(input){
  if(!active)return;
  const samples=new Float32Array(input), duration=samples.length/ctx.sampleRate;
  const rms=Math.sqrt(samples.reduce((sum,v)=>sum+v*v,0)/samples.length);
  const loud=rms>Number($('sensitivity').value)/1000;
  if(!speech){
    preRoll.push(samples);if(preRoll.length>5)preRoll.shift();
    onset=loud?onset+duration:0;
    if(onset<.16)return;
    invalidate(); speech=true;frames=preRoll.slice();total=frames.length*duration;voiced=onset;quiet=0;
    status('Listening… speak your question.');
  }else{frames.push(samples);total+=duration;voiced+=loud?duration:0;quiet=loud?0:quiet+duration;}
  if(quiet>=.85 || total>=19){
    if(voiced>=.3){
      const audio=encodeWav(frames,ctx.sampleRate);
      send('streamlit:setComponentValue',{value:{type:'audio',scope,session,turn,audio},dataType:'json'});
      status('Transcribing locally… You can speak again to replace this turn.');
    }else status('Listening…');
    reset();
  }
}
$('start').onclick=async()=>{
  if(active)return;
  if(!navigator.mediaDevices?.getUserMedia){status('Microphone is unavailable. Open this localhost app in Chrome or Edge.');return;}
  session=crypto.randomUUID();const requestedSession=session;
  $('start').disabled=true;$('stop').disabled=false;status('Waiting for microphone permission…');
  try{
    const mic=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
    if(session!==requestedSession){mic.getTracks().forEach(t=>t.stop());return;}
    stream=mic;ctx=new AudioContext();await ctx.resume();
    source=ctx.createMediaStreamSource(stream);processor=ctx.createScriptProcessor(2048,1,1);
    processor.onaudioprocess=e=>process(e.inputBuffer.getChannelData(0));
    source.connect(processor);processor.connect(ctx.destination); // output remains silent
    active=true;reset();$('stop').disabled=false;$('interrupt').disabled=false;
    status('Listening continuously. Pause briefly when you finish a question.');
    stream.getTracks().forEach(t=>t.onended=()=>{if(active)stop('Microphone disconnected.');});
  }catch(e){stop('Microphone could not start. Check browser permission and microphone availability.');}
};
$('stop').onclick=()=>{session=crypto.randomUUID();stop();};
$('interrupt').onclick=()=>{invalidate();status('Answer interrupted. Listening for your next question…');};
function receiveResponse(r){
  if(!r || !active || r.scope!==scope || r.session!==session || r.turn!==turn || speech)return;
  const id=r.session+':'+r.turn;if(lastReply===id)return;lastReply=id;
  if(r.error){status(r.error+' Listening for another question.');return;}
  $('transcript').textContent='You: '+r.transcript; $('answer').textContent='Copilot: '+r.text;resize();
  const voice=speechSynthesis.getVoices().find(v=>v.localService && /^en\b/i.test(v.lang));
  if(!voice){status('Answer displayed. No local English voice is available; cloud voices are disabled.');return;}
  const utterance=new SpeechSynthesisUtterance(r.text);utterance.voice=voice;utterance.rate=1.05;
  utterance.onend=()=>{if(active && r.turn===turn)status('Listening… ask your next question.');};
  utterance.onerror=()=>{if(active && r.turn===turn)status('Playback unavailable. Answer is displayed; still listening.');};
  speechSynthesis.cancel();speechSynthesis.speak(utterance);status('Speaking. Talk or press Interrupt answer to stop playback.');
}
window.addEventListener('message',e=>{
  if(e.source!==parent || e.data.type!=='streamlit:render')return;
  const args=e.data.args;
  if(scope!==null && scope!==args.scope){session=crypto.randomUUID();stop('Selection changed. Press Start voice to resume.');$('answer').textContent='';$('transcript').textContent='';}
  scope=args.scope;ready=args.ready;$('start').disabled=active||!ready;
  if(!ready)status('Local speech model is not installed. Run python scripts/setup_voice.py.');
  else if(!active)status('Ready. Press Start voice to enable the microphone.');
  receiveResponse(args.response);resize();
});
window.addEventListener('pagehide',()=>stop());
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop('Voice stopped while the page is hidden.');});
send('streamlit:componentReady',{apiVersion:1});resize();
// Stop capture if the component is hidden by a tab switch or scrolled out of view.
if(typeof IntersectionObserver!=='undefined'){
  new IntersectionObserver(entries=>{if(active && !entries[0].isIntersecting)stop('Voice stopped because its controls are no longer visible.');}).observe(document.body);
}
