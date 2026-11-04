/** Playwright MCP regression. Every project API request is intercepted; no inference or rendering runs. */
export async function verifyDraftPersistence(page) {
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const project="f93aa0e0-4ada-463c-a7c5-086ddeecd4b9", media="22222222-2222-4222-8222-222222222222";
  const job="11111111-1111-4111-8111-111111111111", story="55555555-5555-4555-8555-555555555555", video="66666666-6666-4666-8666-666666666666";
  const proposalId="77777777-7777-4777-8777-777777777777", renderId="88888888-8888-4888-8888-888888888888";
  const stamp="2026-11-04T00:00:00Z";
  const storyboard={target_seconds:30,total_seconds:10,cuts:[0,1].map(i=>({media_id:media,source_window_index:i,window_index:i,start_seconds:i*5,end_seconds:(i+1)*5,playback_order:i}))};
  const makeJob=id=>({id,status:"succeeded",created_at:stamp,updated_at:stamp,started_at:stamp,finished_at:stamp,attempt_count:1,error_code:null,progress:null});
  let saved=null, proposals=[], renders=[], failSave=false, renderPolls=0;
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
      if(renders.length) {
        renderPolls++;
        renders[0].status=renderPolls<3?"queued":renderPolls<5?"running":"succeeded";
      }
      return json({items:renders});
    }
    if(path.endsWith("/media")) return json({items:[{id:media,project_id:project,original_filename:"journey.mp4",size_bytes:1024,duration_seconds:60,created_at:stamp,video:{stream_index:0,codec:"h264",width:1920,height:1080,pixel_format:"yuv420p",frame_rate:{numerator:30,denominator:1}},audio:null}],limit:100,offset:0});
    if(path.endsWith("/ai-jobs")) return json({items:[makeJob(job)]});
    if(path.endsWith(`/artifacts/${story}`)) return json(storyboard);
    if(path.endsWith(`/artifacts/${video}`)) return route.fulfill({status:200,contentType:"video/mp4",body:"mock video"});
    if(path.endsWith("/artifacts")) return json({items:[{id:story,kind:"storyboard",size_bytes:300,download_url:`${path}/${story}`},{id:video,kind:"video",size_bytes:1024,download_url:`${path}/${video}`}]});
    if(path.endsWith(`/ai-jobs/${job}`)) return json(makeJob(job));
    if(path.endsWith(`/ai-jobs/${renderId}`)) return json({...makeJob(renderId),status:renders[0]?.status??"queued"});
    return json({items:[]});
  });
  await page.goto("http://127.0.0.1:3001/studio/draft-persistence-qa");
  const header=page.locator(".studio-topbar"), revision=page.locator(".studio-revisionChat"), timeline=page.getByRole("region",{name:"Your draft",exact:true});
  await timeline.getByRole("button",{name:"Select Moment 2",exact:true}).waitFor();
  await revision.getByLabel("What should change?").fill("Move the last moment first");
  const ask=revision.getByRole("button",{name:"Ask for a new order",exact:true});
  assert(await ask.isDisabled(),"Unsaved First Cut blocks revision");
  assert(await header.getByRole("button",{name:/Save Changes/}).count()===0,"Header shows status without Save");
  assert(await timeline.getByRole("button",{name:/Save Changes/}).count()===0,"Timeline retains rendering without Save");
  assert(await page.getByRole("button",{name:"Save Changes",exact:true}).count()===1,"Exactly one Save Changes action exists");
  assert(await revision.getByRole("button",{name:"Save Changes",exact:true}).isEnabled(),"Dirty blocker has actionable Save");
  const screenshots=[];
  for(const width of [1440,1024,375]) {
    await page.setViewportSize({width,height:1000});await page.evaluate(()=>scrollTo(0,0));
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`No page overflow at ${width}`);
    const button=revision.getByRole("button",{name:"Save Changes",exact:true});
    await button.scrollIntoViewIfNeeded();
    const box=await button.boundingBox();assert(box && box.x>=0 && box.x+box.width<=width,`Save fits at ${width}`);
    const path=`/tmp/intentcut-single-save-unsaved-${width}.png`;await page.screenshot({path,fullPage:true});screenshots.push(path);
  }
  await page.setViewportSize({width:1440,height:1000});
  await revision.getByRole("button",{name:"Save Changes",exact:true}).evaluate(b=>{b.click();b.click();});
  await revision.getByRole("button",{name:"Saving…",exact:true}).waitFor();
  assert(await ask.isDisabled(),"Save pending blocks revision");
  await header.getByText(/All changes saved/).waitFor();
  assert(puts.length===1,"Same-tick double save sends one PUT");
  await page.waitForFunction(()=>!document.querySelector('.studio-revisionChat button[type="submit"]').disabled);
  assert(await ask.isEnabled(),"Save automatically enables revision without retyping");
  await page.reload();await header.getByText(/All changes saved/).waitFor();
  await revision.getByLabel("What should change?").fill("Move the last moment first");
  await ask.evaluate(b=>{b.click();b.click();});
  await revision.getByRole("button",{name:"Use this order",exact:true}).waitFor();
  assert(revisions.length===1,"Duplicate revision submits send one POST");
  await revision.getByRole("button",{name:"Use this order",exact:true}).click();
  await header.getByText(/All changes saved · Version 2/).waitFor();
  await page.reload();await header.getByText(/All changes saved · Version 2/).waitFor();
  const firstRange=await timeline.getByRole("button",{name:"Select Moment 1",exact:true}).innerText();
  assert(firstRange.includes("5.0s – 10.0s"),"Accepted order survives refresh");
  await timeline.getByRole("button",{name:"Make my video",exact:true}).evaluate(b=>{b.click();b.click();});
  await timeline.getByText(/Queued ·/).first().waitFor();
  assert(!(await timeline.innerText()).includes("haven’t made a video"),"Queued is never described as absent");
  assert(await timeline.getByRole("button",{name:"Make my video",exact:true}).isDisabled(),"Queued prevents another submission");
  await timeline.getByText(/Rendering ·/).first().waitFor();
  await page.waitForFunction(()=>document.querySelector('.studio-draftPersistence')?.textContent.includes('Your finished video is ready to watch'));
  assert(renderRequests.length===1 && renderRequests[0].revision===2,"Render uses accepted revision (mocked)");
  await page.reload();
  await header.getByText(/Video version 2/).waitFor();
  const picker=page.getByLabel("Choose a version to watch");
  assert(await picker.inputValue()===renderId,"Refresh selects successful manual render");
  await picker.selectOption("");
  assert(await picker.inputValue()==="","First Cut remains separately selectable");
  await picker.selectOption(renderId);
  await timeline.getByRole("button",{name:"Select Moment 1",exact:true}).click();
  await timeline.getByRole("button",{name:"Move later",exact:true}).click();
  const saveCue=timeline.getByRole("link",{name:"Save your draft in AI Director → Rework your story",exact:true});
  await saveCue.click();
  await page.waitForFunction(()=>document.activeElement?.id==="editing-draft-save");
  assert(await page.getByRole("tab",{name:"AI Director",exact:true}).getAttribute("aria-selected")==="true","Timeline save cue opens Director and focuses Save");
  await revision.getByLabel("What should change?").fill("Keep this order");
  assert(await ask.isDisabled(),"Editing disables revision again");
  failSave=true;
  await revision.getByRole("button",{name:"Save Changes",exact:true}).click();
  await header.getByText("Save failed",{exact:true}).waitFor();
  assert((await timeline.getByRole("button",{name:"Select Moment 1",exact:true}).innerText()).includes("0.0s – 5.0s"),"Save failure preserves edits");
  assert(await ask.isDisabled(),"Save failure keeps revision blocked");
  await page.screenshot({path:"/tmp/intentcut-single-save-save-failed-1440.png",fullPage:true});
  failSave=false;
  await revision.getByRole("button",{name:"Retry Save Changes",exact:true}).click();
  await header.getByText(/All changes saved · Version 3/).waitFor();
  assert(await ask.isEnabled(),"Retry success enables revision");
  assert(await revision.getByRole("button",{name:"Save Changes",exact:true}).isDisabled(),"Single Save remains visible and disabled when saved");
  // Timeline-only editing remains saveable even when every moment is removed.
  await timeline.getByRole("button",{name:"Select Moment 1",exact:true}).click();
  await timeline.getByRole("button",{name:"Remove moment",exact:true}).click();
  await timeline.getByRole("button",{name:"Remove moment",exact:true}).click();
  await saveCue.click();
  await revision.getByRole("button",{name:"Save Changes",exact:true}).click();
  await header.getByText(/All changes saved · Version 4/).waitFor();
  assert(saved.window_indices.length===0,"Single Save persists entire draft including empty Timeline");
  assert(await ask.isDisabled(),"Empty draft still blocks revision");
  assert(accepts.length===1 && unexpected.length===0,"No First Cut or unexpected mutations");
  await page.screenshot({path:"/tmp/intentcut-single-save-saved-1440.png",fullPage:true});
  return {passed:true,puts:puts.length,revisions:revisions.length,accepts:accepts.length,mockedRenders:renderRequests.length,screenshots};
}
