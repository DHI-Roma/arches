import $ from 'jquery';
import _ from 'underscore';
import ko from 'knockout';
import arches from 'arches';
import AlertViewModel from 'viewmodels/alert';
import BaseSearchViewComponent from 'views/components/search/base-search-view';
import transitiveSearchViewTemplate from 'templates/views/components/search/transitive-search-view.htm';


const componentName = 'transitive-search-view';
const viewModel = BaseSearchViewComponent.extend({ 
    initialize: async function(sharedStateObject) {
        const self = this;
        BaseSearchViewComponent.prototype.initialize.call(this, sharedStateObject);
        
        this.selectedPopup = ko.observable('');
        this.sharedStateObject.selectedPopup = this.selectedPopup;
        var firstEnabledFilter = _.find(this.sharedStateObject.searchFilterConfigs, function(filter) {
            return filter.config.layoutType === 'tabbed';
        }, this);
        this.selectedTab = ko.observable(firstEnabledFilter.type);
        this.sharedStateObject.selectedTab = this.selectedTab;
        this.resultsExpanded = ko.observable(true);
        this.isResourceRelatable = function(graphId) {
            var relatable = false;
            if (this.graph) {
                relatable = _.contains(this.graph.relatable_resource_model_ids, graphId);
            }
            return relatable;
        };
        this.sharedStateObject.isResourceRelatable = this.isResourceRelatable;
        this.toggleRelationshipCandidacy = function() {
            return function(resourceinstanceid){
                var candidate = _.contains(sharedStateObject.relationshipCandidates(), resourceinstanceid);
                if (candidate) {
                    sharedStateObject.relationshipCandidates.remove(resourceinstanceid);
                } else {
                    sharedStateObject.relationshipCandidates.push(resourceinstanceid);
                }
            };
        };
        this.sharedStateObject.toggleRelationshipCandidacy = this.toggleRelationshipCandidacy;

        this.selectPopup = function(component_type) {
            if(this.selectedPopup() !== '' && component_type === this.selectedPopup()) {
                this.selectedPopup('');
            } else {
                this.selectedPopup(component_type);
            }
        };
        this.resourceModels = ko.observableArray();
        this.filter = ko.observableArray();

        const response = await fetch(arches.urls.api_search_component_data + componentName);
        if (response.ok) {
            const data = await response.json();
            data.resources.forEach(function (res) {
                if (res.is_active === true && !res.source_identifier_id) {
                    self.resourceModels.push(res);
                }
            });
            self.resourceModels.sort(function(a,b) {
                return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
            });  // sort resource model list alphabetically
        } else {
            // eslint-disable-next-line no-console
            console.log('Failed to fetch resource instance list');
        }

        var filterUpdated = ko.computed(function() {
            return JSON.stringify(ko.toJS(this.filter()));
        }, this);
        filterUpdated.subscribe(function() {
            this.updateQuery();
        }, this);

        this.searchFilterVms[componentName](this);
    },

});

export default ko.components.register(componentName, {
    viewModel: viewModel,
    template: transitiveSearchViewTemplate,
});
