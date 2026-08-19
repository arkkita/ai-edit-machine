/* Read-only After Effects project inventory for AI Edit Machine.
 *
 * Input and output paths are supplied through task-specific environment variables:
 *   AI_EDIT_AEP_INPUT
 *   AI_EDIT_AEP_REPORT
 *   AI_EDIT_AE_INSPECTION_CONFIRMED=true
 *
 * The operator must close After Effects and explicitly confirm before launching this
 * script. afterfx.exe -r may reuse an existing instance, so this script never quits
 * the application and refuses to run when a non-empty/open project is visible.
 */

(function () {
    function quoteJson(text) {
        return '"' + String(text)
            .replace(/\\/g, "\\\\")
            .replace(/"/g, '\\"')
            .replace(/\r/g, "\\r")
            .replace(/\n/g, "\\n")
            .replace(/\t/g, "\\t") + '"';
    }

    function stringify(value, indent) {
        var depth = indent || 0;
        var padding = new Array(depth + 1).join("  ");
        var childPadding = new Array(depth + 2).join("  ");
        var parts = [];
        var key;
        var index;
        if (value === null || value === undefined) return "null";
        if (typeof value === "number") return isFinite(value) ? String(value) : "null";
        if (typeof value === "boolean") return value ? "true" : "false";
        if (typeof value === "string") return quoteJson(value);
        if (value instanceof Array) {
            if (value.length === 0) return "[]";
            for (index = 0; index < value.length; index += 1) {
                parts.push(childPadding + stringify(value[index], depth + 1));
            }
            return "[\n" + parts.join(",\n") + "\n" + padding + "]";
        }
        for (key in value) {
            if (value.hasOwnProperty(key) && typeof value[key] !== "function") {
                parts.push(childPadding + quoteJson(key) + ": " + stringify(value[key], depth + 1));
            }
        }
        if (parts.length === 0) return "{}";
        return "{\n" + parts.join(",\n") + "\n" + padding + "}";
    }

    function scalar(value) {
        if (value === null || value === undefined) return null;
        if (typeof value === "number" || typeof value === "string" || typeof value === "boolean") {
            return value;
        }
        if (value instanceof Array) {
            var result = [];
            for (var index = 0; index < value.length; index += 1) result.push(scalar(value[index]));
            return result;
        }
        try { return value.toString(); } catch (ignored) { return "[unserializable]"; }
    }

    function propertyRecord(property, includeChildren, depth) {
        var record = {
            name: property.name,
            match_name: property.matchName,
            property_type: property.propertyType,
            enabled: property.enabled === undefined ? null : property.enabled,
            active: property.active === undefined ? null : property.active,
            children: []
        };
        try {
            if (property.propertyType === PropertyType.PROPERTY) {
                record.value = scalar(property.value);
                record.num_keys = property.numKeys;
                record.keys = [];
                for (var keyIndex = 1; keyIndex <= property.numKeys; keyIndex += 1) {
                    record.keys.push({
                        time_seconds: property.keyTime(keyIndex),
                        value: scalar(property.keyValue(keyIndex))
                    });
                }
            }
        } catch (valueError) {
            record.value_error = valueError.toString();
        }
        if (includeChildren && depth < 5) {
            try {
                for (var childIndex = 1; childIndex <= property.numProperties; childIndex += 1) {
                    record.children.push(propertyRecord(property.property(childIndex), true, depth + 1));
                }
            } catch (childError) {
                record.children_error = childError.toString();
            }
        }
        return record;
    }

    function layerRecord(layer) {
        var sourceName = null;
        try { sourceName = layer.source ? layer.source.name : null; } catch (ignored) {}
        var record = {
            index: layer.index,
            name: layer.name,
            source_name: sourceName,
            enabled: layer.enabled,
            locked: layer.locked,
            shy: layer.shy,
            solo: layer.solo,
            adjustment_layer: layer.adjustmentLayer,
            three_d_layer: layer.threeDLayer,
            blending_mode: layer.blendingMode.toString(),
            start_time_seconds: layer.startTime,
            in_point_seconds: layer.inPoint,
            out_point_seconds: layer.outPoint,
            stretch_percent: layer.stretch,
            time_remap_enabled: layer.timeRemapEnabled,
            effects: [],
            transform: null,
            time_remap: null
        };
        var effects = layer.property("ADBE Effect Parade");
        if (effects) {
            for (var effectIndex = 1; effectIndex <= effects.numProperties; effectIndex += 1) {
                record.effects.push(propertyRecord(effects.property(effectIndex), true, 0));
            }
        }
        var transform = layer.property("ADBE Transform Group");
        if (transform) record.transform = propertyRecord(transform, true, 0);
        var timeRemap = layer.property("ADBE Time Remapping");
        if (timeRemap) record.time_remap = propertyRecord(timeRemap, true, 0);
        return record;
    }

    function itemRecord(item) {
        var record = { id: item.id, name: item.name, type_name: item.typeName };
        if (item instanceof CompItem) {
            record.kind = "composition";
            record.width = item.width;
            record.height = item.height;
            record.pixel_aspect = item.pixelAspect;
            record.duration_seconds = item.duration;
            record.frame_rate = item.frameRate;
            record.work_area_start_seconds = item.workAreaStart;
            record.work_area_duration_seconds = item.workAreaDuration;
            record.layers = [];
            for (var layerIndex = 1; layerIndex <= item.numLayers; layerIndex += 1) {
                record.layers.push(layerRecord(item.layer(layerIndex)));
            }
        } else if (item instanceof FootageItem) {
            record.kind = "footage";
            record.width = item.width;
            record.height = item.height;
            record.duration_seconds = item.duration;
            record.frame_rate = item.frameRate;
            try { record.file_name = item.file ? item.file.name : null; } catch (ignored) {}
            record.missing = item.footageMissing;
        } else if (item instanceof FolderItem) {
            record.kind = "folder";
        }
        return record;
    }

    function normalizedPath(fileOrFolder) {
        return String(fileOrFolder.fsName).replace(/\\/g, "/").toLowerCase();
    }

    function isInsideRoot(file, root) {
        var candidate = normalizedPath(file);
        var rootPath = normalizedPath(root).replace(/\/$/, "");
        return candidate.indexOf(rootPath + "/") === 0;
    }

    function writeCreateNewVerified(outputFile, body) {
        if (outputFile.exists) throw new Error("Report target already exists; choose a new artifact name.");
        var parent = outputFile.parent;
        if (!parent.exists) throw new Error("Report directory does not exist: " + parent.fsName);
        var temporary = null;
        var attempt;
        for (attempt = 0; attempt < 20; attempt += 1) {
            temporary = new File(parent.fsName + "/." + outputFile.name + "." +
                String(new Date().getTime()) + "." + String(Math.floor(Math.random() * 1000000)) +
                ".partial");
            if (!temporary.exists) break;
        }
        if (!temporary || temporary.exists) throw new Error("Could not allocate a new temporary report.");
        temporary.encoding = "UTF-8";
        if (!temporary.open("w")) throw new Error("Could not create temporary report.");
        temporary.write(body);
        temporary.close();
        temporary.encoding = "UTF-8";
        if (!temporary.open("r")) throw new Error("Could not reopen temporary report for verification.");
        var verification = temporary.read();
        temporary.close();
        if (verification !== body) {
            temporary.remove();
            throw new Error("Temporary report verification failed.");
        }
        if (!temporary.rename(outputFile.name)) {
            temporary.remove();
            throw new Error("Could not atomically publish the report.");
        }
    }

    var inputPath = $.getenv("AI_EDIT_AEP_INPUT");
    var outputPath = $.getenv("AI_EDIT_AEP_REPORT");
    var scriptFile = new File($.fileName);
    var outputRootPath = scriptFile.parent.parent.fsName + "/artifacts/reference-analysis";
    var report = {
        inspection_version: "1.1.0",
        input_name: inputPath ? new File(inputPath).name : null,
        app_version: app.version,
        project_items: [],
        error: null
    };
    var dialogsSuppressed = false;
    var inspectionProjectOpened = false;
    try {
        if (!inputPath || !outputPath) {
            throw new Error("Required inspection environment variables are missing.");
        }
        if (!scriptFile.exists) throw new Error("Inspection must run from the audited script file.");
        if ($.getenv("AI_EDIT_AE_INSPECTION_CONFIRMED") !== "true") {
            throw new Error("Inspection requires explicit confirmation that After Effects was closed first.");
        }
        var sourceFile = new File(inputPath);
        var outputFile = new File(outputPath);
        var outputRoot = new Folder(outputRootPath);
        if (!sourceFile.exists) throw new Error("AEP input does not exist: " + inputPath);
        if (!outputRoot.exists) throw new Error("Approved report root does not exist.");
        if (!isInsideRoot(outputFile, outputRoot)) throw new Error("Report must be inside the approved analysis root.");
        if (normalizedPath(sourceFile) === normalizedPath(outputFile)) {
            throw new Error("AEP input and report output must not collide.");
        }
        if (app.project && (app.project.file || app.project.numItems > 0)) {
            throw new Error("An After Effects project is already open; aborting to protect the user session.");
        }
        app.beginSuppressDialogs();
        dialogsSuppressed = true;
        app.open(sourceFile);
        inspectionProjectOpened = true;
        report.project_name = app.project.file ? app.project.file.name : null;
        for (var itemIndex = 1; itemIndex <= app.project.numItems; itemIndex += 1) {
            report.project_items.push(itemRecord(app.project.item(itemIndex)));
        }
        app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);
        inspectionProjectOpened = false;
    } catch (error) {
        report.error = error.toString();
        try {
            if (inspectionProjectOpened && app.project) {
                app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);
                inspectionProjectOpened = false;
            }
        } catch (ignoredClose) {}
    }
    try {
        if (!outputPath) throw new Error("No safe report target was supplied.");
        var finalOutputFile = new File(outputPath);
        var finalOutputRoot = new Folder(outputRootPath);
        if (!finalOutputRoot.exists || !isInsideRoot(finalOutputFile, finalOutputRoot)) {
            throw new Error("Report target is outside the approved analysis root.");
        }
        if (inputPath && normalizedPath(new File(inputPath)) === normalizedPath(finalOutputFile)) {
            throw new Error("AEP input and report output must not collide.");
        }
        writeCreateNewVerified(finalOutputFile, stringify(report, 0));
    } catch (writeError) {
        // AfterFX.com will expose this failure on its console if file access is disabled.
        $.writeln("Could not write inspection report: " + writeError.toString());
    }
    if (dialogsSuppressed) app.endSuppressDialogs(false);
}());
