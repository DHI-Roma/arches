define([
    'jquery',
    'underscore',
    'knockout',
    'arches',
    'viewmodels/alert',
    'views/components/search/base-search-view',
    'templates/views/components/search/standard-search-view.htm',
], function($, _, ko, arches, AlertViewModel, BaseSearchViewComponent, standardSearchViewTemplate) {
    const componentName = 'standard-search-view';
    const viewModel = BaseSearchViewComponent.extend({ 
        initialize: function(sharedStateObject) {
            const self = this;
            BaseSearchViewComponent.prototype.initialize.call(this, sharedStateObject);
            
            this.selectedPopup = ko.observable('');
            this.sharedStateObject.selectedPopup = this.selectedPopup;
            this.searchQueryId = ko.observable(null);
            this.sharedStateObject.searchQueryId = this.searchQueryId;
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
            this.searchFilterVms[componentName](this);
        },

        doQuery: function() {
            const queryObj = JSON.parse(this.queryString());
            if (self.updateRequest) { self.updateRequest.abort(); }
            self.updateRequest = $.ajax({
                type: "GET",
                url: arches.urls.search_results,
                data: queryObj,
                context: this,
                success: function(response) {
                    _.each(this.sharedStateObject.searchResults, function(value, key, results) {
                        if (key !== 'timestamp') {
                            delete this.sharedStateObject.searchResults[key];
                        }
                    }, this);
                    _.each(response, function(value, key, response) {
                        if (key !== 'timestamp') {
                            this.sharedStateObject.searchResults[key] = value;
                        }
                    }, this);
                    this.sharedStateObject.searchResults.timestamp(response.timestamp);
                    this.searchQueryId(this.sharedStateObject.searchResults.searchqueryid);
                    this.sharedStateObject.userIsReviewer(response.reviewer);
                    this.sharedStateObject.userid(response.userid);
                    this.sharedStateObject.total(response.total_results);
                    this.sharedStateObject.hits(response.results.hits.hits.length);
                    this.sharedStateObject.alert(false);
                },
                error: function(response, status, error) {
                    const alert = new AlertViewModel('ep-alert-red', arches.translations.requestFailed.title, response.responseJSON?.message);
                    if(self.updateRequest.statusText !== 'abort'){
                        this.alert(alert);
                    }
                    this.sharedStateObject.loading(false);
                },
                complete: function(request, status) {
                    self.updateRequest = undefined;
                    window.history.pushState({}, '', '?' + $.param(queryObj).split('+').join('%20'));
                    this.sharedStateObject.loading(false);
                }
            });
        },
    });

    return ko.components.register(componentName, {
        viewModel: viewModel,
        template: standardSearchViewTemplate,
    });
});
