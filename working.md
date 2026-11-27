# Fengrid Development - Scratch Pad

## To Do's

### Settings/Preferences interface

- [x] Add a Settings/Preferences screen and a main menu button.
- [x] Move/locate all of Fengrids main settings and configuration options to this screen.
  - [x] Take inspiration from VS Code's settings/preferences UI.
- [x] Create a "first run" configuration routine that allows the user to define system paths, asset folders, visual theme/layout options, and Fengrid's core features.
  - [x] Use this screen to get the initial definition for asset folders, and run the initial asset scan/ingest routine while the user configures the rest of the options.
  - [x] Keep everything within a single screen that's shown once to the user, on the first time the application runs, and save all their preferences to the main Settings/Preferences. Direct the user to the main menu where the Settings/Preferences are if they wish to modify/change anything.

### Multiple Databases, network shares

- [x] Add support for multiple "databases". By "database", I mean the top-level heirarchical entity where all of the projects, libraries, collections, assets, and metadata reside (even if that is technically implemented as one of multiple tables in a single SQLite database, or multiple SQLite databases feeding into a single Fengrid "database".
  - [x] Only one Fengrid database can be actively loaded at any one time.
  - [x] If a user creates or opens a new Fengrid database, any existing databases will be listed under a "Recent" menu, and they can optionally be starred so they're listed in a "Quick Access" database menu, so they can be quickly switched to/from.
- [x] Add support for local, network, and cloud storage backends.
  - [x] Include support for local directories, local network shares (SMB), NFS, SSHFS, S3-compatible.
  - [x] Add a note saying support for syncing data with personal cloud storage services is coming soon.

### Search/command bar, slash commands

Add a combination search, configure, and command bar to the top that expands and opens in the main UI if the user presses the primary hotkey `Alt` + `~` (or `Option` + `~` on Macs).

- [x] Allow the user to define their own keyboard shortcut if they prefer. Make this preference part of the "first run" configuration, as it will be one of the primary mechanisms for navigating and searching in Fengrid.
- [x] Use the placeholder text in the command bar at the top to provide a tip to the user for the `Alt` + `~` keyboard shortcut (or whatever the shortcut has been defined as).
- [x] Functions like a cross between the command bar in VS Code, Spotlight search on MacOS, and the snippet search features in "Dash" or "Alfred" (Dash and Alfred are both developer productivity apps for MacOS).

### Import/Export/Backup

Add a complete featureset for ingesting/importing/exporting assets, collections, libraries, and projects; backing up the application and its data; and managing the SQLite database.

Include an interface in the Settings/Preferences screen for utilizing these functions:

### **Importing/ingesting assets to Fengrid**

- [x] Support for a variety of import formats.
- [x] Keep an eye on memory management and performance, in the case of large quantities of data.
- [x] Preferences for whether the asset files should be *copied* into the application folder (embedded), or *linked* to an external location  (linking requires correct permissions for the local filesystem(s)).
- [x] Add options for automated format conversion with support for a variety of target formats.
- [x] Automated renaming options with support for prefixes, suffixes, and find/replace using regex. Also supports cardinal enumeration, randomized enumeration, generated GUIDs, and/or supplied CSV data.
- [x] Optional support for local and network "watch folders" or "dropboxes" (that are scanned periodically for changes) provided through the local filesystem/FTP/SFTP/SCP/HTTP/rsync/cloud storage (Amazon S3-compatible for now--OneDrive, iCloud, and Google Drive support should be listed as "Coming Soon!")

### **Export assets, collections, libraries, and projects**

- [x] Support for a variety of export formats.
- [x] Options for choosing multiple export formats.
- [x] Options for running scripts or batch operations on the items selected for export.
- [x] In addition to the standard format options, include an extended suite of export options that would be useful and specific for each asset type (icons, fonts, color schemes, code snippets). Things such as image resizing or coloring for `Icons`, packaging style/weight variants and/or webfonts for `Fonts`, or including a text list of HEX/HSL/RGB/CMYK/etc. codes for colors included in the export.

Fengrid should essentially eliminate the user's need for file conversion websites, or having to use Photoshop to apply a color filter across some icons.

### **Fengrid Backup & Restore**

The application and its data should be available as a backup package in one `*.tar.gz` archive that contains:

- [x] A structured file (`.json`, `.yaml`, `.xml`, etc.), with:
  - [x] Version/build details
  - [x] System settings
  - [x] User preferences
  - [x] Configuration options
  - [x] Local environment details
  - [x] Logs/troubleshooting/debugging data (if present)
- [x] A full copy of the SQLite database(s)
- [x] Platform-specific restore scripts that:
  - [x] Download Fengrid using the same release version tag as recorded in the backup.
  - [x] Checks for any current/existing Fengrid installations or running Fengrid servers/processes, and if found, informs the user that the script must be run on a system where Fengrid is not actively installed or running.
  - [x] Copies/imports the settings/configuration files
  - [x] Copies/imports the SQLite database(s)
  - [x] Handles permissions, different usernames, different systems/OS's, etc. automatically, unless doing so isn't possible, in which case it should fail gracefully and output an error code with a clear reason.

### **Fengrid REST API**

Scaffold and instantiate a REST API specification for Fengrid, add a lightweight API middleware and task scheduler to handle requests.

- [x] Create a new directory `./api/v1`.
- [x] Create a Postman collection for futher development.
- [x] Include a thorough set of actions, features, and options for controlling Fengrid via its REST API: ingest/import/export/distribute/characterize/inventory/describe/copy/edit/update/save/tag/collect/reference/list all collected/tracked assets, their relevant metadata, and their associated collections and libraries.

### General UI Tweaks

- [x] In the Fonts pane's left panel, move the list of Families to beneath the list of font types.
- [x] Add the ability to collapse lists in the left panel.  
- [x] Add support for 7-color color schemes in the Colors pane.
- [x] The top bar in the Colors pane doesn't change when switched to Terminal Color Themes mode. Be sure the content/buttons/info in the top bar is relevant to the rest of the interface.
- [x] Add generated unique GUID's to each tracked asset and every collection, library, and project in Fengrid. Place these in a default field that's added to all tracked assets named `guid`.
- [x] Add a default field to all tracked assets `slug`. Be sure values in the field `slug` are unique, `slug` is empty by default.
- [x] Add support for other types of digital assets: images, videos, audio files, documents, structured data (json, xml, yml, csv, sql, etc.), spatial data (GIS/GPS/GNSS), timeseries data (with graphs, visualizations, MQTT streams), and Markdown documents. These assets also receive generated unique GUID's when first ingested.
- [x] Asset types that involve structured data may receive updates via external sensors and services. Allow for this asset data to be created, read, updated, and deleted (CRUD) using the REST API and/or with websockets.
- [x] Add support for linking directly to other tracked assets in Snippets and Project code.
  - [x] Create a namespace/path convention using the asset's type (icon/font/code/image/data/docs/file)>namespace (library)>collection>asset name.
  - [x] Use the `slug` field to allow users to define short, unique "slugs" for each tracked asset for linking to the asset easily using `[[ slug ]]`, so `img src="[[ slug ]]"`would show whichever asset is being referenced (presumably an image).
  - [x] Add a function for linking to assets using their path/name wrapped in square brackets, so `img src="[[ icon/adwaita/devices/audio-headphones-symbolic ]]"` would show the Adwaita headphones icon.
  - [x] Add a function for linking to assets using their generated GUID's wrapped in square brackets `[[ GUID ]]`, so `img src="[[ GUID ]]"` would show whichever asset is being referenced (presumably an image)

### **Fengit**

Implement `git` revision control for Fengrid's projects and libraries (Fengrid's collections are entirely local/internal functions). Use `git-lfs` or `git-annex` for tracking larger files and/or asset folders with a very large quantity of files. Automatically set these things up for the user (running `git init` and creating a default branch `fengrid-main`, tracking the status, reminding the user to commit their changes, etc.), and provide them the option to define access tokens for a remote code forge (Github/Codeberg/Forgejo/Gitea/etc.) in the Settings/Preference screen.

- [x] Also provide some internal history features to enable `Undo` and `Redo` for most of Fengrid's various fields, functions, options, and actions. Be sure to add checks/protections when performing bulk actions on large amounts of data, the history should have a strict memory limit and be disabled altogether for bulk actions.
- [x] Each Project and/or Library is a git repo.
- [x] Branches/worktrees can be used to work independently or experiment with variations without affecting the default `fengrid-main` Project tree.
- [x] Users can use pull requests to merge their branches/worktrees back into `fengrid-main`, with guided step-by-step rebasing if/when needed.
- [x] Push remotes are optional.
- [x] Project's git repos start with a default branch `fengrid-main`, which forms an initial snapshot of the project. Commits can be made directly to `fengrid-main` when a user "Saves" their project.
- [x] Provide the user with an easy way to create new working branches when preparing to work with a Project, and prompt the user to commit their changes regularly.
- [x] After the work is finished, offer to merge the working branch back into the default `fengrid-main` branch.
- [x] Whenever a working branch is merged, offer to delete it for the user. If they say "yes", confirm the deletion with an explicit warning.
- [x] Add a button to the Settings/Preferences screen for this feature to perform maintenance on all Project repositories. This will look for any uncommitted changes, dangling branches that have already been merged, and attempt to clean things up.
- [x] Batch operations and batch processing in Projects (or on the assets that are associated with a Project) will automatically create new branches before making any changes. Once the operation is complete, it will prompt the user to review the results, and select to either commit or discard them. Once the changes have been committed, Fengrid will automatically merge everything back to the default working branch, and delete the batch operation's branch/worktree.
- [x] Provide a source control interface similar to GittyUp or VS Code: show the Project's active worktree, staged/unstaged changes, and current status. Add small buttons for performing common git actions.
- [x] If a Project has uncommited changes pending when Fengrid is closed, prompt the user to commit or stash the changes before closing.
- [x] If a Project has uncommitted changes, remind the user with a discrete but bright red message in the status bar to commit/stash their changes.

---

### **Fengrid Plugins**

Create Fengrid "clients" for all popular graphics and frontend development apps.

- [ ] Include Figma, Adobe CC, LightRoom, DaVinci Resolve, Shotwell, Inkscape, VS Code, Sublime Text, Jetbrains IDEs
- [ ] **Importing assets to other applications**: Make it so the user--from the UI of Adobe Photoshop, for example--can open a window to preview and browse/search/filter their assets in a highly performant, elegant Fengrid UI. Select assets to import to their Photoshop project, optionally configure batch actions, and have them added directly as new layers.
- [ ] **Ingesting assets from other applications**: Provide a convenient, performant, and intuitive interface for adding assets to Fengrid's database directly from other applications. For example, a user selects all of the shapes in an Adobe Illustrator file, opens the Fengrid plugin, and adds all of the selected objects as individual assets, with options for naming/enumeration and batch processing.
- [ ] **REST API clients**: Create intuitive, Fengrid styled GUI's to facilitate common actions from the Fengrid REST API that have been adapted to the context and scope of the host application.
- [ ] Be sure to maintain awareness of potential security and stability problems, and do NOT expose Fengrid or its users/hosts to any unneccessary risks or known vulnerabilities.

---

### **Code Review & Pre-Release Evaluation**

- [x] Create a new branch from `dev-qt`, name it `v1.0.0-rc1-testing`
- [x] Carefully evaluate this project for quality, efficiency, security, and accessbility.
- [x] Do not attempt to troubleshoot, diagnose, or repair any issues you find. Instead, record them in `ISSUES.md` and open new Github Issues for later action.
- [x] Create a TODO.md for any low-priority follow-ups or tasks that need attention, but don't warrant their own dedicated Github Issue.
  - [x] File a single Github Issue titled `TODO for v1.0.0-rc1-testing` and use `TODO.md` to detail the tasks and provide a single place to manage them.
- [x] Open a new Github Issue for any security vulnerabilities or medium-to-high priority quality issues you find.
- [ ] Ensure it's using the most appropriate and effective approach to executing its broader goals and scope.
  - [x] Identify significant bottlenecks and performance challenges, and assess whether the project's *architecture* is the root cause, or just our particular implementation/approach. Open a new Github Issue with your findings, and any recommendations.
- [x] Look for any quality issues.
- [x] Ensure all scripts, binaries, and services are function nominally, do not present any significant performance or security vulnerabilities, include tests and protections against crashing/unexpected termination, and output valid/useful log information if they encounter errors/warnings.
- [x] Ensure the visual layouts are pixel-perfect.
- [x] Make sure none of the UI elements are overflowing or bunching up.
- [x] Ensure the UI's layout and general workflows for each pane/interface are intuitive and clear. If you see any potentially redundant, unhelpful, irrelevant, or erroneous UI elements, make a note of them in `TODO.md` for further attention/work.
- [ ] Ensure there are no security vulnerabilities in the asset import/ingestion/scanning/processing routines.  Include tests and protections against crashing/unexpected termination, and output valid/useful log information if the import/export process encounters any errors/warnings. Create a new Github Issue with any potential vulnerabilities you find.
- [x] Implement field validation and input sanitization for all data ingestion functions and user interactions, if it's not already.
- [x] Ensure there are no security vulnerabilities in the live preview functions. Include tests and protections against crashing/unexpected termination, and output valid/useful log information if the import/export process encounters any errors/warnings. Create a new Github Issue with any potential vulnerabilities you find.
- [x] Run the application, and check the console for any errors or warnings, record this to a log file `console.log`, if there are any serious warnings or errors then open Github Issues to report them.
- [x] Push all documentation and changes to `v1.0.0-rc1-testing`, write ALL changes in the `dev-qt` branch (since it was created) to `CHANGELOG.md`.
- [x] Open a Pull Request to merge `v1.0.0-rc1-testing`  with `dev`. Add a comment to the PR that explains this `v1.0.0-rc1-testing`branch is for testing the new QT6 platform, identifying/addressing all of the issues present (include 17 79.05 39115 INFO: Build complete! The results are available in: /work/qt/dist

#### 17 79.24 gl-strip: libxcb-xkb.so.1

#### 17 79.2a list with links to all of the open issues). All issues should be addressed before merging `v1.0.0-rc1-testing`  with `dev` (`dev` branch will be the staging branch for the eventual `v1.0.0` release)

---

### Revamp the shortcuts for exporting assets

- [x] Integrate the export shortcuts in the asset panes with the main export features
- [x] Export buttons should open an interface for selecting format(s), destination, and options.
- [x] For CSS font exports, simply show a window with the relevant CSS boilerplate (in a text box with syntax highlighting so the user can customize it) that automatically includes all the user's selected fonts in `WOFF`/`WOFF2` format. Offer to save this CSS to a file along with the fonts in `WOFF2` format (which is also how the fonts should be referenced in the generated CSS, using relative paths pointing to `WOFF`/`WOFF2` font files included in the export package).

---

- [x]  ## Preset Libraries
  - Add a Documentation tab to the properties inspector panel for asset libraries and Projects that displays content from README.md
  - Add a License tab to the properties inspector panel for asset libraries and Projects that displays summarized details from LICENSE.md if it's a standard open source license, and a link to the LICENSE.md.
  - Add a Sources tab to the properties inspector panel for asset libraries and Projects that displays summarized details from the relevant asset's configured git repository (if one exists), and includes button shortcuts to common `git` commands.
  - Be sure that all asset collections, libraries, and Projects remain distinct to their respective panes, ie-so `Icon` collections are not displayed on the other panes, and the same for other asset types.
  - Only show collections and libraries with assets that can be displayed in the active pane.
  - Use tags to draw taxonomic links between assets and entities of different types.

    Create a curated set of preset asset libraries and their assets using other open-source projects (see below).

  - These libraries are tracked like any other, but marked as `remote` by default, and only downloaded on-demand when they are selected.
  - Use Fengrid's built-in git functions to clone the repository using the source URLs and branches selected in their Library properties.
  - Make the default grid size on the `Projects` pane the same size as Github's "social images".
  - Show an icon in the preset libaries' preview grid square indicating they are not locally present. If Libraries *are* downloaded, use their README.md and/or  social images from their Github repo to generate a corresponding preview image.

    1. Search Github for open source fonts to add to a preset font Library; Note: Do NOT download the fonts, rather include their names/URL so the user can browse them, but with a default icon in the preview grid square(s) that indicate they need to be downloaded.
    2. Search Github for open source icon sets to add to a preset icon Library; Note: Do NOT download the icons, rather include their names/URL so the user can browse them, but with a default icon in the preview grid square(s) that indicate they need to be downloaded.
    3. Search Github for open source static site themes/templates to add to a preset Projects Library; Note: Do NOT download the themes/templates, rather include their names/URL so the user can browse them, but with a default icon in the preview grid square(s) that indicate they need to be downloaded.

    Add preset libraries configured with the projects' git remote URLs, and using scraped details/summary in their metadata/taxonomy, tagged using context from their `README.md`, and marked as `remote` so they do not get downloaded/initialized by default.

---

## Icon Pane

## Colors Pane

## Fonts Pane

- [x] When a font is right-clicked, the properties inspector closes, which causes the layout to shift, and it's very confusing. Leave the property inspector open unless a different asset is **left-clicked** (in which case the property inspector should show the clicked asset). If **right-clicked**, the context menu should open for the selected asset/item while the property inspector and its current selection remains.

## Snippets Pane

- [x] The code editor's cursor does not line up properly, it appears to be nearly a full character's width off of its actual position.

## Projects Pane

The Projects Pane needs a complete rework. It doesn't currently function as intended in any capacity. Forget everything about how the Project Pane is designed/laid out, and start from scratch with:

- [x] I want you to create a Figma-killer. A complete frontend design and development tool for planning, developing, constructing, testing, packaging, exporting, distributing, tweaking, previewing, measuring, analyzing, documenting, organizing, managing, collecting, characterizing, sharing, and archiving projects and their assets.
  - [x] Create multiple screens that can be accessed in the Projects pane to implement all of these functions. The function list above is in no particular order. Use industry standards, best practices, and inspiration from apps like Figma, Dreamweaver, and VS Code to construct a complete, intuitive, and polished suite of interfaces, panels, menus, dialogs, that are organized and laid out so that they can best facilitate the Project pane's goal of being a powerful WYSIWYG frontend UI viewer, editor, and manager.
  - [x] Use Fengrid's asset management, revision control, and relational linking schemes to allow users to construct their projects using collections and libraries of Fengrid-tracked artifacts and assets.
  - [x] Use templating features so the user's projects can be generalized across multiple implementations and/or tenants.
  - [x] Create integrations with Docker so users can configure Projects to deploy in Docker containers, with options to attach to running containers and use Fengrid's tools with the assets and artifacts in the container's local storage, and live browser previews using Docker's networking features.

## General/Misc

- [x] The Settings screen still will not open. The program freezes/crashes, and has to be force-closed.
- [x] Allow the user to hold `Ctrl` or `Shift` to select multiple items. Add checkboxes to the previews for selecting assets.
  - [x] **Empty** checkboxes are *only* displayed when the mouse hovers over the preview. However, when any given box *is* **checked**, then *all* checkboxes are visible on *all* previews to indicate to the user that multiple previews can be selected.
- [x] Start with all attribute lists in the left panel collapsed by default. Remember their state throughout the session, but reset them all to collapsed when the app restarts.
- [x] Remove the "Add folder" button at the bottom of the attribute lists on the left panel. Add a discrete, sticky `Import Assets` button at the bottom of the left panel that launches the import interface.
- [x] Replace the icon set used in Fengrids UI with something more subtle. Also be sure they're all consistently sized/scaled, the icons along the top bar are all over the map.
- [x] Allow custom fields to be created from any Pane's property inspector.
- [x] Collections don't work in the Colors pane, and are missing entirely in the Fonts pane. Collections and Smart Collections should be available for all asset types.
- [x] Create a json collection with a list of short Japanese haiku, lines from famous poems, and lines from famous speeches to use as the default preview text in the Fonts pane (choose  a random one from this list each time the Pane is opened).

---

- [ ] Blur the main UI when modular windows like the Preset Libraries are open.
- [ ] Fix the spacing on buttons in the Preset Libraries window
- [ ] Open the Preset Libraries window so that the relevant active Pane's libraries are displayed (so if I click on a Preset Libary in the Fonts pane, it opens to font libraries).
- [ ] Combine all Library types and Collection types into single respective lists in the left panel. Preset Libraries and User Libraries (or Smart Collections and User Collections) should all be listed together as simply `Libraries` and `Collections`, but with indicators to signify if they're smart/remote preset/local preset.

---

- [ ] The submenu in the right-click menu is broken, it doesn't respond and stays open regardless of what is being selected.
- [ ] Add a crash handler and debug/troubleshooting log that gets saved to Fengrid's application folder. On the following launch, ask the user if they'd like to download the crash report.

Do a broad quality assurance sweep, open a new Github Issue for any extant problems or concerns you detect. Be sure that the user interface is pixel-perfect and looking sharp, all functions are fully working, the API server is responsive to requests, the taxonomies and schema are coherent, the architecture makes sense, and the choices made have generally been correct.

## Errors
