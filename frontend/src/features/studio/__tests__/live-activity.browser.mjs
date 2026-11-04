/** Playwright MCP regression. Every project API request is intercepted; no inference or rendering runs. */
export async function verifyLiveActivity(page, videoBase64) {
  const videoBytes=Buffer.from(videoBase64,"base64");
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const project="f93aa0e0-4ada-463c-a7c5-086ddeecd4b9", media="22222222-2222-4222-8222-222222222222";
  const job="11111111-1111-4111-8111-111111111111", story="55555555-5555-4555-8555-555555555555", video="66666666-6666-4666-8666-666666666666";
  const proposalId="77777777-7777-4777-8777-777777777777", renderId="88888888-8888-4888-8888-888888888888";
  const stamp="2026-11-04T00:00:00Z";
  const storyboard={target_seconds:30,total_seconds:10,cuts:[0,1].map(i=>({media_id:media,source_window_index:i,window_index:i,start_seconds:i*5,end_seconds:(i+1)*5,playback_order:i}))};
  const makeJob=id=>({id,status:"succeeded",created_at:stamp,updated_at:stamp,started_at:stamp,finished_at:stamp,attempt_count:1,error_code:null,progress:null});
  let saved={revision:3,base_job_id:job,base_artifact_id:story,window_indices:[0,1],updated_at:stamp,storyboard}, proposals=[], renders=[{job_id:renderId,revision:3,status:"queued"},{job_id:"99999999-9999-4999-8999-999999999999",revision:2,status:"succeeded"}], failSave=false, renderPolls=0;
  let renderGets=0, videoGets=0;
  const puts=[], revisions=[], accepts=[], renderRequests=[], unexpected=[];
  await page.unrouteAll({behavior:"wait"});
  await page.route("**/projects/**",async route=>{
    const request=route.request(), path=new URL(request.url()).pathname, method=request.method();
    const json=body=>route.fulfill({json:body});
    if(method!=="GET") {
      if(method==="PUT" && path.endsWith("/edit-draft")) {
        const body=request.postDataJSON(); puts.push(body);
        await new Promise(resolve=>setTimeout(resolve,180));
        if(failSave) return route.fulfill({status:503,json:{code:"unavailable",message:"Save unavailable"}});
        if(body.expected_revision!==(saved?.revision??0)) return route.fulfill({status:409,json:{code:"draft_conflict",message:"Changed"}});
        saved={revision:(saved?.revision??0)+1,base_job_id:body.base_job_id,base_artifact_id:body.base_artifact_id,window_indices:body.window_indices,updated_at:stamp,storyboard};
        return json(saved);
      }
      if(method==="POST" && path.endsWith("/proposals")) {
        const body=request.postDataJSON();revisions.push(body);
        await new Promise(resolve=>setTimeout(resolve,180));
        assert(body.draft_revision===saved.revision,"Revision must use saved server revision");
        proposals=[{id:proposalId,draft_id:project,base_revision:saved.revision,base_job_id:job,base_artifact_id:story,instruction:body.instruction,state:"pending",job_status:"succeeded",error_code:null,before:saved.window_indices,after:[...saved.window_indices].reverse(),explanation:"Requested order",reasons:[],changes:{removed:[],reordered:true},applied_revision:null,progress:null}];
        return json({id:proposalId});
      }
      if(method==="POST" && path.endsWith("/accept")) {
        const body=request.postDataJSON();accepts.push(body);assert(body.expected_revision===saved.revision,"Acceptance preserves optimistic concurrency");
        saved={...saved,revision:saved.revision+1,window_indices:proposals[0].after};
        proposals=[{...proposals[0],state:"accepted",applied_revision:saved.revision}];
        return json({proposal:proposals[0],draft:saved});
      }
      if(method==="POST" && path.endsWith("/renders")) {
        renderRequests.push(request.postDataJSON());renders=[{job_id:renderId,revision:saved.revision,status:"queued"}];return json({id:renderId});
      }
      unexpected.push(`${method} ${path}`);return route.fulfill({status:400,json:{code:"blocked",message:"Unexpected test mutation"}});
    }
    if(path.includes("/by-slug/") || path===`/projects/${project}`) return json({id:project,name:"Draft Persistence QA",slug:"draft-persistence-qa",created_at:stamp});
    if(path.endsWith("/edit-draft")) return json({draft:saved});
    if(path.endsWith("/proposals")) return json({items:proposals});
    if(path.endsWith("/renders")) {
      renderGets++;
      if(renderGets===2) return route.fulfill({status:503,json:{message:"Transient failure"}});
      if(renders.length) {
        renderPolls++;
        renders[0].status=renderPolls<3?"queued":renderPolls<5?"running":"succeeded";
      }
      return json({items:renders});
    }
    if(path.endsWith("/media")) return json({items:[{id:media,project_id:project,original_filename:"journey.mp4",size_bytes:1024,duration_seconds:60,created_at:stamp,video:{stream_index:0,codec:"h264",width:1920,height:1080,pixel_format:"yuv420p",frame_rate:{numerator:30,denominator:1}},audio:null}],limit:100,offset:0});
    if(path.endsWith("/ai-jobs")) return json({items:[makeJob(job)]});
    if(path.endsWith(`/artifacts/${story}`)) return json(storyboard);
    if(path.endsWith(`/artifacts/${video}`)) {videoGets++;return route.fulfill({status:200,contentType:"video/mp4",body:videoBytes});}
    if(path.endsWith("/artifacts")) return json({items:[{id:story,kind:"storyboard",size_bytes:300,download_url:`${path}/${story}`},{id:video,kind:"video",size_bytes:videoBytes.length,download_url:`${path}/${video}`}]});
    if(path.endsWith("/ai-jobs/99999999-9999-4999-8999-999999999999")) return json(makeJob("99999999-9999-4999-8999-999999999999"));
    if(path.endsWith(`/ai-jobs/${job}`)) return json(makeJob(job));
    if(path.endsWith(`/ai-jobs/${renderId}`)) return json({...makeJob(renderId),status:renders[0]?.status??"queued"});
    return json({items:[]});
  });

  await page.goto("http://127.0.0.1:3001/");
  await page.evaluate(project=>sessionStorage.removeItem(`intentcut:preview:${project}`),project);
  await page.goto("http://127.0.0.1:3001/studio/live-activity-qa");
  const activity=page.locator('section[aria-labelledby="processing-heading"]');
  const monitor=page.locator('.studio-monitor');
  await activity.getByText('Version 3 — Queued — Waiting for worker',{exact:true}).first().waitFor();
  await activity.getByText('Version 3 — Rendering video',{exact:true}).first().waitFor();
  await activity.getByText('Version 3 — Your video is ready',{exact:true}).first().waitFor();
  const player=monitor.locator('video');
  await player.waitFor();
  await page.waitForFunction(()=>document.querySelector('.studio-monitor video')?.readyState>=2);
  await player.evaluate(v=>v.play());
  assert(await player.evaluate(v=>!v.paused),'Fixture MP4 plays without refresh');
  assert(videoGets===1,'One video download for the completed source');
  const source=await player.getAttribute('src');
  const count=renderGets;
  await page.waitForTimeout(4500);
  assert(renderGets===count,'Terminal render list stops polling');
  assert(await player.getAttribute('src')===source,'Unchanged source does not remount');
  const picker=page.getByLabel('Choose a version to watch');
  for(const selected of ['99999999-9999-4999-8999-999999999999','',renderId]){
    await picker.selectOption(selected);
    await player.waitFor();
    await page.waitForFunction(()=>document.querySelector('.studio-monitor video')?.readyState>=2);
    assert(await picker.inputValue()===selected,'Picker tracks chosen source');
  }
  await picker.selectOption('99999999-9999-4999-8999-999999999999');
  await page.reload();await player.waitFor();
  await page.waitForFunction(()=>document.querySelector('.studio-monitor video')?.readyState>=2);
  assert(await picker.inputValue()==='99999999-9999-4999-8999-999999999999','Refresh preserves explicit Version 2 selection');
  await activity.getByText('Version 3 — Your video is ready',{exact:true}).first().waitFor();
  await activity.getByText('Revision & render history',{exact:true}).click();
  assert(await activity.getByText('Version 2 — Your video is ready',{exact:true}).isVisible(),'Version 2 history persists');
  assert(await activity.locator('summary').filter({hasText:'First Cut · succeeded'}).isVisible(),'First Cut history retained');
  for(const width of [1440,1024,375]){
    await page.setViewportSize({width,height:1000});await activity.scrollIntoViewIfNeeded();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No page overflow');
    await page.screenshot({path:`/tmp/intentcut-video-activity-${width}.png`,fullPage:true});
  }
  assert(unexpected.length===0 && puts.length===0 && revisions.length===0 && renderRequests.length===0,'No job submissions');
  return {passed:true,renderGets,videoGets};
}
