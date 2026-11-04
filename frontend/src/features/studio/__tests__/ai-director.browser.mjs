/** Run with Playwright MCP browser_run_code_unsafe: pass this exported function as code.
 * All project API traffic is intercepted; this test never starts inference.
 */
export async function verifyDirectorRecovery(page) {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const project = "f93aa0e0-4ada-463c-a7c5-086ddeecd4b9";
  const media = "22222222-2222-4222-8222-222222222222";
  const oldId = "11111111-1111-4111-8111-111111111111";
  const newId = "33333333-3333-4333-8333-333333333333";
  const laterId = "44444444-4444-4444-8444-444444444444";
  const storyId = "55555555-5555-4555-8555-555555555555";
  const videoId = "66666666-6666-4666-8666-666666666666";
  const stamp = "2026-01-01T00:00:00Z";
  const brief = {kind:"first_cut",intent:"A quiet cinematic journey",target_seconds:45,media_ids:[media]};
  const makeJob = (id, status) => ({id,status,created_at:stamp,updated_at:stamp,started_at:null,finished_at:status === "failed" || status === "succeeded" ? stamp : null,attempt_count:1,error_code:status === "failed" ? "secret-provider-exception" : null,progress:null});
  const failed = makeJob(oldId,"failed");
  const unchanged = JSON.stringify(failed);
  let jobs = [];
  let posts = [];
  let draft = null;
  let missingVideo = false;
  let missingMedia = false;
  const storyboard = {target_seconds:45,total_seconds:5,cuts:[{media_id:media,window_index:0,start_seconds:0,end_seconds:5,playback_order:0}]};
  const projectRecord = {id:project,name:"Director Recovery",slug:"director-recovery",created_at:stamp};
  const mutations = [];
  await page.unrouteAll({behavior:"wait"});
  await page.route("**/projects/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = body => route.fulfill({json:body});
    if (request.method() !== "GET") {
      mutations.push(`${request.method()} ${path}`);
      if (request.method() === "POST" && path === `/projects/${project}/ai-jobs`) {
        posts.push(request.postDataJSON());
        // Hold the response briefly to exercise double-click and pending guards.
        await new Promise(resolve => setTimeout(resolve,250));
        jobs = [makeJob(newId,"queued"),...jobs];
        return route.fulfill({status:202,json:{id:newId,status:"queued",status_url:`/projects/${project}/ai-jobs/${newId}`}});
      }
      return route.fulfill({status:400,json:{code:"unexpected_mutation",message:"Test blocked mutation"}});
    }
    if (path.includes("/by-slug/") || path === `/projects/${project}`) return json(projectRecord);
    if (path === `/projects/${project}/media`) return json({items:missingMedia ? [] : [{id:media,project_id:project,original_filename:"journey.mp4",size_bytes:1024,duration_seconds:60,created_at:stamp,video:{stream_index:0,codec:"h264",width:1920,height:1080,pixel_format:"yuv420p",frame_rate:{numerator:30,denominator:1}},audio:null}],limit:100,offset:0});
    if (path === `/projects/${project}/ai-jobs`) return json({items:jobs});
    if (path.endsWith("/edit-draft")) return json({draft});
    if (path.endsWith(`/artifacts/${storyId}`)) return json(storyboard);
    if (path.endsWith("/artifacts")) {
      const base = path;
      return json({items:[{id:storyId,kind:"storyboard",size_bytes:300,download_url:`${base}/${storyId}`},...missingVideo ? [] : [{id:videoId,kind:"video",size_bytes:1024,download_url:`${base}/${videoId}`}]]});
    }
    const job = jobs.find(item => path === `/projects/${project}/ai-jobs/${item.id}`);
    if (job) return json(job);
    return json({items:[]});
  });
  await page.goto("http://127.0.0.1:3001/studio/director-recovery");
  const director = page.getByRole("tabpanel",{name:"AI Director"});
  const rework = director.getByRole("heading",{name:"Rework your story"});
  await director.getByLabel("Your story idea").waitFor();
  await page.waitForFunction(() => !document.querySelector('#creative-intent')?.disabled);
  assert(await rework.count() === 0,"Rework must be absent initially");

  jobs = [failed];
  await page.evaluate(({project,oldId,brief}) => {
    sessionStorage.clear();
    sessionStorage.setItem(`intentcut:first-cut-inputs:${project}:${oldId}`,JSON.stringify(brief));
  },{project,oldId,brief});
  await page.reload();
  const retry = director.getByRole("button",{name:"Try again",exact:true});
  await retry.waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent === 'Try again' && !b.disabled));
  const failureHeading = director.getByRole("heading",{name:"We couldn’t create your first cut"});
  await failureHeading.waitFor();
  const headingBox = await failureHeading.boundingBox();
  const retryBox = await retry.boundingBox();
  assert(headingBox && retryBox,"Failure message and Try again must both be visible");
  assert(retryBox.y >= headingBox.y + headingBox.height,"Try again must sit immediately below the failure message");
  assert(retryBox.y < headingBox.y + headingBox.height + 800,"Try again must be visible without scrolling past unrelated sections");
  assert(await rework.count() === 0,"Rework must be absent on first failure");
  assert(!(await director.innerText()).includes("secret-provider-exception"),"Internal errors must stay private");
  for (const width of [1440,1024,375]) {
    await page.setViewportSize({width,height:1000});
    await director.scrollIntoViewIfNeeded();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),`No page overflow at ${width}`);
    await page.screenshot({path:`/tmp/intentcut-director-failed-${width}.png`,fullPage:true});
  }
  await page.setViewportSize({width:1440,height:1000});
  // Two synchronous clicks exercise the ref lock before React can rerender.
  await retry.evaluate(button => {button.click();button.click();});
  await director.getByRole("heading",{name:"Waiting to start",exact:true,level:3}).waitFor();
  assert(posts.length === 1,"Double-click must create exactly one job");
  assert(JSON.stringify(posts[0]) === JSON.stringify(brief),"Retry must preserve all original inputs");
  assert(jobs[0].id !== oldId && JSON.stringify(failed) === unchanged,"Failed job must remain unchanged in history");
  assert(await rework.count() === 0,"Rework must be absent while queued");
  assert(await director.locator('button[type="submit"]').first().isDisabled(),"Queued blocks create");
  // Deliberately stale storage must not override the server's newest active job.
  await page.evaluate(({project,oldId}) => sessionStorage.setItem(`intentcut:ai-job:${project}`,oldId),{project,oldId});
  await page.reload();
  await director.getByRole("heading",{name:"Waiting to start",exact:true,level:3}).waitFor();
  assert(await page.evaluate(project => sessionStorage.getItem(`intentcut:ai-job:${project}`),project) === newId,"Refresh restores the new job from server state");
  jobs[0] = {...jobs[0],status:"running",started_at:stamp,progress:{stage:"understanding_footage",stage_started_at:stamp,updated_at:stamp,completed_windows:20,total_windows:30}};
  await director.getByText("20 of 30 moments checked").waitFor();
  assert(await rework.count() === 0,"Rework must be absent while running");
  await page.reload();
  await director.getByText("20 of 30 moments checked").waitFor();
  assert(await director.locator('button[type="submit"]').first().isDisabled(),"Running blocks create after refresh");
  jobs[0] = makeJob(newId,"succeeded");
  await rework.waitFor();
  await page.screenshot({path:"/tmp/intentcut-director-succeeded-1440.png",fullPage:true});
  await page.reload();
  await rework.waitFor();
  // Persisted saved draft survives a newer failed job, independently of latest status.
  draft = {revision:1,base_job_id:newId,base_artifact_id:storyId,window_indices:[0],updated_at:stamp,storyboard};
  jobs = [makeJob(laterId,"failed"),...jobs];
  await page.reload();
  await rework.waitFor();
  await director.getByRole("heading",{name:"We couldn’t create your first cut"}).waitFor();
  await director.getByLabel("What should change?").fill("Move the last moment first");
  assert(await director.getByRole("button",{name:"Ask for a new order"}).isEnabled(),"Earlier saved cut remains revisable after failure and refresh");
  await page.screenshot({path:"/tmp/intentcut-director-earlier-success-1440.png",fullPage:true});

  missingVideo = true;
  await page.reload();
  await director.getByRole("heading",{name:"We couldn’t create your first cut"}).waitFor();
  assert(await rework.count() === 0,"Storyboard without video must not reveal Rework");
  draft = null; jobs = [failed]; missingVideo = false;
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await director.getByText(/original story idea or selected footage/).waitFor();
  assert(await director.getByLabel("Your story idea").isEditable(),"Missing original inputs allow form editing");
  assert(await rework.count() === 0,"First failure still has no Rework");
  await page.evaluate(({project,oldId,brief}) => sessionStorage.setItem(`intentcut:first-cut-inputs:${project}:${oldId}`,JSON.stringify(brief)),{project,oldId,brief});
  missingMedia = true;
  await page.reload();
  await director.getByText(/original story idea or selected footage/).waitFor();
  assert(await director.locator('button[type="submit"]').first().isDisabled(),"Deleted source media prevents resubmission");
  assert(mutations.length === 1 && posts.length === 1,"Only one mocked POST; no job mutations or inference");
  return {passed:true,posts:posts.length,history:jobs.map(job=>({id:job.id,status:job.status})),screenshots:[1440,1024,375].map(width=>`/tmp/intentcut-director-failed-${width}.png`)};
}
