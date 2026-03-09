odoo.define("acs_hms_base.acs", function (require) {
    "use strict";
    var rpc = require("web.rpc");
    var core = require("web.core");

    core.bus.on("web_client_ready", null, function () {
        // Get block_ui data from backend
        rpc.query({
            model: "res.company",
            method: "acs_get_blocking_data",
        }).then(function (block_data) {
            // UI name
            if (block_data.name && block_data.name !== "False") {
                var block_ui = $('<div class="acs-block_ui hidden"/>');
                $("body").append(block_ui);
                //block_ui.hide();
                block_ui.html(block_data.name);
                block_ui.show();
            }
        });
    });
});
