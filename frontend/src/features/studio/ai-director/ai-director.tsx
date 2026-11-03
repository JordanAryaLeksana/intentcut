import { ConnectedDirector } from "./connected-director";

interface AIDirectorProps {
  projectId?: string;
}

export function AIDirector({ projectId }: AIDirectorProps) {
  return (
    <section
      className="studio-panel studio-director"
      aria-labelledby="director-heading"
      data-tour="director"
    >
      <header className="studio-panelHeader">
        <h2 id="director-heading">
          <span className="studio-directorMark" aria-hidden="true">
            ✳
          </span>
          AI Director
        </h2>
        <span>Your story partner</span>
      </header>

      {projectId ? (
        <ConnectedDirector
          key={projectId}
          projectId={projectId}
        />
      ) : (
        <div className="studio-directorBody">
          <p className="studio-overline">Your story, your direction</p>
          <h3>A creative partner, with your vision in mind.</h3>
          <p>Create a project and add your footage to begin.</p>
        </div>
      )}
    </section>
  );
}