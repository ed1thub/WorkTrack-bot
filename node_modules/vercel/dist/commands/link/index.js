import { createRequire as __createRequire } from 'node:module';
import { fileURLToPath as __fileURLToPath } from 'node:url';
import { dirname as __dirname_ } from 'node:path';
const require = __createRequire(import.meta.url);
const __filename = __fileURLToPath(import.meta.url);
const __dirname = __dirname_(__filename);
import {
  getSubcommand
} from "../../chunks/chunk-YPQSDAEW.js";
import {
  addSubcommand7 as addSubcommand,
  getCommandAliases,
  linkCommand
} from "../../chunks/chunk-HJVSVCAZ.js";
import "../../chunks/chunk-4LDQIDKG.js";
import "../../chunks/chunk-NIOGCTVR.js";
import "../../chunks/chunk-HAJ2XRTQ.js";
import "../../chunks/chunk-GCKUEAUE.js";
import "../../chunks/chunk-3NSIZGHP.js";
import "../../chunks/chunk-JZLADLMF.js";
import {
  detectExplicitScope,
  getScope
} from "../../chunks/chunk-PR72OE3G.js";
import "../../chunks/chunk-ONYQGA2O.js";
import {
  ensureLink
} from "../../chunks/chunk-3GJFG6GX.js";
import "../../chunks/chunk-QV34LTI7.js";
import "../../chunks/chunk-4L73BR7G.js";
import {
  autoInstallVercelPlugin
} from "../../chunks/chunk-RYUPBGRO.js";
import {
  help
} from "../../chunks/chunk-IS56OO2J.js";
import "../../chunks/chunk-KSIISCB2.js";
import {
  addRepoLink,
  ensureRepoLink
} from "../../chunks/chunk-JJ36CB7A.js";
import {
  TelemetryClient
} from "../../chunks/chunk-4OEA5ILS.js";
import "../../chunks/chunk-AXQNAI65.js";
import "../../chunks/chunk-CO5D46AG.js";
import {
  getFlagsSpecification,
  parseArguments,
  printError
} from "../../chunks/chunk-GQLARSTH.js";
import {
  cmd
} from "../../chunks/chunk-EBEBY45K.js";
import {
  output_manager_default
} from "../../chunks/chunk-ZQKJVHXY.js";
import "../../chunks/chunk-S7KYDPEM.js";
import "../../chunks/chunk-TZ2YI2VH.js";

// src/util/telemetry/commands/link/index.ts
var LinkTelemetryClient = class extends TelemetryClient {
  trackCliArgumentCwd() {
    this.trackCliArgument({
      arg: "cwd",
      value: this.redactedValue
    });
  }
  trackCliFlagRepo(flag) {
    if (flag) {
      this.trackCliFlag("repo");
    }
  }
  trackCliFlagYes(yes) {
    if (yes) {
      this.trackCliFlag("yes");
    }
  }
  trackCliFlagConfirm(flag) {
    if (flag) {
      this.trackCliFlag("confirm");
    }
  }
  trackCliOptionProject(project) {
    if (project) {
      this.trackCliOption({
        option: "project",
        value: this.redactedValue
      });
    }
  }
  trackCliOptionTeam(value) {
    if (value) {
      this.trackCliOption({
        option: "team",
        value: this.redactedValue
      });
    }
  }
  trackCliOptionProjectId(value) {
    if (value) {
      this.trackCliOption({
        option: "project-id",
        value: this.redactedValue
      });
    }
  }
  trackCliSubcommandAdd(actual) {
    this.trackCliSubcommand({
      subcommand: "add",
      value: actual
    });
  }
};

// src/commands/link/index.ts
var COMMAND_CONFIG = {
  add: getCommandAliases(addSubcommand)
};
async function link(client) {
  let parsedArgs = null;
  const flagsSpecification = getFlagsSpecification(linkCommand.options);
  try {
    parsedArgs = parseArguments(client.argv.slice(2), flagsSpecification, {
      permissive: true
    });
  } catch (error) {
    printError(error);
    return 1;
  }
  const { subcommand, subcommandOriginal } = getSubcommand(
    parsedArgs.args.slice(1),
    COMMAND_CONFIG
  );
  const telemetry = new LinkTelemetryClient({
    opts: {
      store: client.telemetryEventStore
    }
  });
  function printHelp(command) {
    output_manager_default.print(
      help(command, { parent: linkCommand, columns: client.stderr.columns })
    );
  }
  if (subcommand === "add") {
    if (parsedArgs.flags["--help"]) {
      telemetry.trackCliFlagHelp("link", subcommandOriginal);
      printHelp(addSubcommand);
      return 2;
    }
    telemetry.trackCliSubcommandAdd(subcommandOriginal);
    const yes2 = !!parsedArgs.flags["--yes"];
    try {
      await addRepoLink(client, client.cwd, { yes: yes2 });
    } catch (err) {
      output_manager_default.prettyError(err);
      return 1;
    }
    await autoInstallVercelPlugin(client, {
      autoConfirm: yes2
    });
    return 0;
  }
  try {
    parsedArgs = parseArguments(client.argv.slice(2), flagsSpecification);
  } catch (error) {
    printError(error);
    return 1;
  }
  if (parsedArgs.flags["--help"]) {
    telemetry.trackCliFlagHelp("link");
    output_manager_default.print(help(linkCommand, { columns: client.stderr.columns }));
    return 2;
  }
  telemetry.trackCliFlagRepo(parsedArgs.flags["--repo"]);
  telemetry.trackCliFlagYes(parsedArgs.flags["--yes"]);
  telemetry.trackCliOptionProject(parsedArgs.flags["--project"]);
  if ("--confirm" in parsedArgs.flags) {
    telemetry.trackCliFlagConfirm(parsedArgs.flags["--confirm"]);
    output_manager_default.warn("`--confirm` is deprecated, please use `--yes` instead");
    parsedArgs.flags["--yes"] = parsedArgs.flags["--confirm"];
  }
  const yes = !!parsedArgs.flags["--yes"];
  let cwd = parsedArgs.args[1];
  if (cwd) {
    telemetry.trackCliArgumentCwd();
    output_manager_default.warn(
      `The ${cmd("vc link <directory>")} syntax is deprecated, please use ${cmd(
        `vc link --cwd ${cwd}`
      )} instead`
    );
  } else {
    cwd = client.cwd;
  }
  if (parsedArgs.flags["--repo"]) {
    output_manager_default.warn(`The ${cmd("--repo")} flag is in alpha, please report issues`);
    try {
      await ensureRepoLink(client, cwd, { yes, overwrite: true });
    } catch (err) {
      output_manager_default.prettyError(err);
      return 1;
    }
  } else {
    const explicitScopeProvided = detectExplicitScope(client);
    if (explicitScopeProvided) {
      await getScope(client, { resolveLocalScope: true });
    }
    const linkNonInteractive = client.nonInteractive || client.argv.includes("--non-interactive");
    const link2 = await ensureLink("link", client, cwd, {
      autoConfirm: yes,
      forceDelete: true,
      projectName: parsedArgs.flags["--project"],
      successEmoji: "success",
      nonInteractive: linkNonInteractive,
      searchAcrossTeams: !explicitScopeProvided
    });
    if (typeof link2 === "number") {
      return link2;
    }
  }
  await autoInstallVercelPlugin(client, {
    autoConfirm: yes
  });
  return 0;
}
export {
  link as default
};
